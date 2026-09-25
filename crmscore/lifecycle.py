"""Lifecycle service. Every agent and every MCP tool calls into this one place.

    bootstrap -> monitor -> build challengers -> gates -> promote or hold
              -> score and write back -> audit      (repeat every period)
    rollback and approve are available at any time.

Deterministic by design. Agents decide which step to run and explain it; the
steps themselves behave the same way every time.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

from . import baseline
from .drift import feature_drift, performance, psi_band, psi_numeric, segment_auc
from .features import FeatureSpec, period_range, shift_period, spec_for
from .model import ScoringModel
from .warehouse import Warehouse, now

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "lifecycle.yaml"


def load_config(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_CONFIG) as fh:
        return yaml.safe_load(fh)


def _dump_model(model: ScoringModel) -> str:
    buf = io.BytesIO()
    joblib.dump(model, buf, compress=3)
    return base64.b64encode(buf.getvalue()).decode()


def _load_model(blob: str) -> ScoringModel:
    return joblib.load(io.BytesIO(base64.b64decode(blob)))


class Lifecycle:
    def __init__(self, warehouse: Warehouse, crm, config: dict | None = None):
        self.wh = warehouse
        self.crm = crm
        self.cfg = config or load_config()
        self._data: dict[str, pd.DataFrame] = {}
        self._models: dict[str, ScoringModel] = {}

    # ================================================================== config and data
    def ocfg(self, obj: str) -> dict:
        return self.cfg["objects"][obj]

    def gcfg(self, obj: str) -> dict:
        return self.cfg["gates"][obj]

    def data(self, obj: str, periods: list[str] | None = None, labeled: bool = False) -> pd.DataFrame:
        if obj not in self._data:
            self._data[obj] = self.wh.load_object_data(obj)
        df = self._data[obj]
        if periods is not None:
            df = df[df["period"].isin(periods)]
        if labeled:
            df = df[df[spec_for(obj).label].notna()]
        return df.reset_index(drop=True)

    def refresh_data(self, obj: str | None = None) -> None:
        for o in ([obj] if obj else list(self._data)):
            self._data.pop(o, None)

    def windows(self, obj: str, period: str) -> dict:
        """Out-of-time split for a cycle at `period`.

        holdout  = newest labeled period. Never trained on. Champion and challengers meet here.
        recent   = the labeled period before it. Split by record id: part trains, part calibrates.
        train    = `train_periods` full periods before `recent`, plus the training part of `recent`.
        finetune = `finetune_periods` full periods before `recent`, plus the training part of `recent`.
        Splitting `recent` gets new behaviour into training one period sooner.
        """
        s, c = spec_for(obj), self.ocfg(obj)
        f = s.period_freq
        holdout = shift_period(period, f, -c["label_lag"])
        recent = shift_period(holdout, f, -1)
        train = period_range(shift_period(recent, f, -c["train_periods"]), shift_period(recent, f, -1), f)
        finetune = period_range(shift_period(recent, f, -c["finetune_periods"]), shift_period(recent, f, -1), f)
        available = set(self.data(obj)["period"].unique())
        return {"period": period, "holdout": holdout, "recent": recent, "calib": recent,
                "train": [p for p in train if p in available] + [recent],
                "finetune": [p for p in finetune if p in available] + [recent]}

    def _split_recent(self, obj: str, win: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return (train, finetune, calib, holdout) frames for a cycle window."""
        s = spec_for(obj)
        recent = self.data(obj, [win["recent"]], labeled=True)
        share = self.ocfg(obj).get("calib_share", 0.5)
        bucket = pd.util.hash_pandas_object(recent[s.id_col], index=False).to_numpy() % 1000
        in_calib = bucket < int(share * 1000)
        calib, recent_train = recent[in_calib], recent[~in_calib]
        older = [p for p in win["train"] if p != win["recent"]]
        older_ft = [p for p in win["finetune"] if p != win["recent"]]
        train = pd.concat([self.data(obj, older, labeled=True), recent_train], ignore_index=True)
        ft = pd.concat([self.data(obj, older_ft, labeled=True), recent_train], ignore_index=True)
        hold = self.data(obj, [win["holdout"]], labeled=True)
        return train, ft, calib.reset_index(drop=True), hold

    def _recency_weights(self, obj: str, df: pd.DataFrame, anchor: str) -> np.ndarray:
        s, hl = spec_for(obj), self.ocfg(obj)["recency_half_life"]
        a = pd.Period(anchor, freq=s.period_freq)
        age = df["period"].map(lambda p: (a - pd.Period(p, freq=s.period_freq)).n).to_numpy(dtype=float)
        return 0.5 ** (age / hl)

    # ================================================================== registry
    def registry(self, obj: str | None = None) -> pd.DataFrame:
        sql = ("SELECT version, object, status, method, parent_version, created_at, train_window, calib_period, "
               "holdout_period, metrics, gates, importance, approved_by, promoted_at, retired_at, notes "
               "FROM MODEL_REGISTRY")
        df = self.wh.query(sql + (" WHERE object = ?" if obj else ""), [obj] if obj else None)
        if len(df):
            df["_n"] = df["version"].str.extract(r"-v(\d+)$").astype(int)
            df = df.sort_values(["object", "_n"]).drop(columns="_n").reset_index(drop=True)
        return df

    def champion_version(self, obj: str) -> str | None:
        df = self.wh.query("SELECT version FROM MODEL_REGISTRY WHERE object = ? AND status = 'champion'", [obj])
        return None if df.empty else df["version"].iat[0]

    def model_row(self, version: str) -> dict:
        df = self.wh.query("SELECT * FROM MODEL_REGISTRY WHERE version = ?", [version])
        if df.empty:
            raise ValueError(f"unknown model version {version}")
        row = df.iloc[0].to_dict()
        for k in ("metrics", "gates", "importance"):
            row[k] = json.loads(row[k]) if row.get(k) else {}
        return row

    def load(self, version: str) -> ScoringModel:
        if version not in self._models:
            blob = self.wh.query("SELECT artifact FROM MODEL_REGISTRY WHERE version = ?", [version])["artifact"].iat[0]
            self._models[version] = _load_model(blob)
        return self._models[version]

    def champion(self, obj: str) -> tuple[str, ScoringModel]:
        v = self.champion_version(obj)
        if v is None:
            raise RuntimeError(f"no champion for {obj}; run bootstrap first")
        return v, self.load(v)

    def _next_version(self, obj: str) -> str:
        n = self.wh.query("SELECT COUNT(*) AS n FROM MODEL_REGISTRY WHERE object = ?", [obj])["n"].iat[0]
        return f"{obj}-v{int(n) + 1}"

    def _register(self, obj: str, model: ScoringModel, method: str, parent: str | None, win: dict,
                  metrics: dict, importance: dict, status: str, notes: str = "", train_window: str = "") -> str:
        import platform

        import sklearn
        version = self._next_version(obj)
        metrics = {**metrics, "runtime": {"python": platform.python_version(), "scikit_learn": sklearn.__version__}}
        self.wh.write("MODEL_REGISTRY", pd.DataFrame([{
            "version": version, "object": obj, "status": status, "method": method,
            "parent_version": parent or "", "created_at": now(),
            "train_window": train_window or f"{win['train'][0]}..{win['train'][-1]}",
            "calib_period": win["calib"], "holdout_period": win["holdout"],
            "metrics": json.dumps(metrics), "gates": json.dumps({}), "importance": json.dumps(importance),
            "artifact": _dump_model(model), "approved_by": "", "promoted_at": "", "retired_at": "", "notes": notes,
        }]))
        self._models[version] = model
        return version

    def _update(self, version: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
        self.wh.execute(f"UPDATE MODEL_REGISTRY SET {sets} WHERE version = ?", vals + [version])

    # ================================================================== evaluation helpers
    def _evaluate(self, obj: str, model: ScoringModel, df: pd.DataFrame) -> dict:
        s, g = spec_for(obj), self.gcfg(obj)
        p = model.predict_proba(df)
        m = performance(df[s.label].to_numpy(), p)
        m["segments"] = segment_auc(df, s.label, p, g["segment_by"], g["segment_min_rows"], g["segment_min_positives"])
        return m

    def _importance(self, model: ScoringModel, df: pd.DataFrame) -> dict:
        sample = df.sample(min(len(df), 600), random_state=1) if len(df) else df
        return model.global_importance(sample) if len(sample) else {}

    # ================================================================== bootstrap
    def bootstrap(self, obj: str, actor: str = "bootstrap") -> str:
        if self.champion_version(obj):
            return self.champion_version(obj)
        s, b = spec_for(obj), self.ocfg(obj)["bootstrap"]
        win = {"train": period_range(b["train"][0], b["train"][1], s.period_freq),
               "calib": b["calib"], "holdout": b["holdout"], "finetune": []}
        train = self.data(obj, win["train"], labeled=True)
        calib = self.data(obj, [win["calib"]], labeled=True)
        hold = self.data(obj, [win["holdout"]], labeled=True)
        model = ScoringModel(s).fit(train, calib, self._recency_weights(obj, train, win["calib"]))
        metrics = {"holdout": self._evaluate(obj, model, hold)}
        v = self._register(obj, model, "bootstrap", None, win, metrics, self._importance(model, hold), "champion",
                           notes="Initial champion trained on the bootstrap window.")
        self._update(v, approved_by=actor, promoted_at=now())
        self.wh.audit(actor, "bootstrap_champion", obj, win["holdout"], v, {"holdout_auc": metrics["holdout"]["auc"]})
        return v

    # ================================================================== monitor
    def monitor(self, obj: str, period: str, actor: str = "monitor-agent") -> dict:
        s, mon, c = spec_for(obj), self.cfg["monitor"], self.ocfg(obj)
        champ_v, champ = self.champion(obj)
        row = self.model_row(champ_v)
        tw = row["train_window"].split("..")
        ref_periods = period_range(tw[0], tw[-1], s.period_freq)
        ref = self.data(obj, ref_periods)
        cur = self.data(obj, [period])
        problems = s.validate(cur)
        drift = feature_drift(ref, cur, s)
        score_psi = psi_numeric(pd.Series(champ.score(ref)), pd.Series(champ.score(cur)))

        holdout = shift_period(period, s.period_freq, -c["label_lag"])
        lab = self.data(obj, [holdout], labeled=True)
        perf = performance(lab[s.label].to_numpy(), champ.predict_proba(lab)) if len(lab) else {}
        base_auc = row["metrics"].get("holdout", {}).get("auc")
        auc_drop = round(base_auc - perf["auc"], 4) if perf.get("auc") and base_auc else None

        # Counterfactuals for the dashboard: the first model frozen in time, and the v0 rules.
        frozen = self.load(f"{obj}-v1")
        frozen_auc = performance(lab[s.label].to_numpy(), frozen.predict_proba(lab))["auc"] if len(lab) else None
        rules_auc = performance(lab[s.label].to_numpy(), baseline.score_v0(obj, lab))["auc"] if len(lab) else None

        unseen = {r["feature"]: {"share": r["unseen_share"], "values": r["unseen_values"]}
                  for _, r in drift[drift["kind"] == "categorical"].iterrows() if r["unseen_share"] > 0}
        max_unseen = max([u["share"] for u in unseen.values()], default=0.0)
        top = drift.iloc[0]
        gap = perf.get("calibration_gap")

        findings, recs = [], set()
        status = "healthy"

        def bump(level):
            nonlocal status
            order = {"healthy": 0, "watch": 1, "action": 2}
            status = level if order[level] > order[status] else status

        for _, r in drift.iterrows():
            band = psi_band(r["psi"], mon["psi_watch"], mon["psi_action"])
            if band != "stable":
                bump("watch" if band == "watch" else "action")
                findings.append(f"{s.labels.get(r['feature'], r['feature'])} input drift PSI {r['psi']:.2f} ({band})")
                if band == "action":
                    recs.update(["finetune", "retrain"])
        if max_unseen >= mon["unseen_share_action"]:
            bump("action")
            for f, u in unseen.items():
                findings.append(f"New {s.labels.get(f, f).lower()} values the champion has never seen: "
                                f"{', '.join(u['values'])} ({u['share']:.0%} of records)")
            recs.add("retrain")
        if auc_drop is not None:
            if auc_drop >= mon["auc_drop_action"]:
                bump("action")
                recs.update(["finetune", "retrain"])
                findings.append(f"AUC down {auc_drop:.3f} vs promotion baseline on {holdout} outcomes")
            elif auc_drop >= mon["auc_drop_watch"]:
                bump("watch")
                findings.append(f"AUC down {auc_drop:.3f} vs promotion baseline (watch)")
        if gap is not None:
            if abs(gap) >= mon["calibration_gap_action"]:
                bump("action")
                recs.add("recalibrate")
                findings.append(f"Scores run {'hot' if gap > 0 else 'cold'} by {abs(gap) * 100:.1f} points on {holdout}")
            elif abs(gap) >= mon["calibration_gap_watch"]:
                bump("watch")
                recs.add("recalibrate")
                findings.append(f"Calibration gap {gap * 100:+.1f} points (watch)")
        if problems:
            bump("action")
            findings.extend(problems)

        report = {
            "object": obj, "period": period, "champion": champ_v, "status": status,
            "labels_through": holdout, "n_current": len(cur), "contract_violations": problems,
            "feature_drift": drift.to_dict("records"), "score_psi": round(score_psi, 4),
            "unseen_categories": unseen, "performance": perf, "promotion_baseline_auc": base_auc,
            "auc_drop": auc_drop, "frozen_v1_auc": frozen_auc, "rules_v0_auc": rules_auc,
            "findings": findings or ["No material drift. Champion is healthy."],
            "recommended_methods": [m for m in self.cfg["methods_cost_order"] if m in recs],
        }
        self.wh.write("DRIFT_REPORTS", pd.DataFrame([{
            "object": obj, "period": period, "champion_version": champ_v, "status": status,
            "max_psi": float(top["psi"]), "top_feature": top["feature"],
            "report": json.dumps(report, default=str), "created_at": now()}]))
        self.wh.audit(actor, "monitor", obj, period, champ_v,
                      {"status": status, "findings": report["findings"], "recommended": report["recommended_methods"]})
        return report

    # ================================================================== build challengers
    def build_challengers(self, obj: str, period: str, methods: list[str], actor: str = "builder-agent") -> dict:
        s, c = spec_for(obj), self.ocfg(obj)
        champ_v, champ = self.champion(obj)
        win = self.windows(obj, period)
        train, ft, calib, hold = self._split_recent(obj, win)
        champ_metrics = self._evaluate(obj, champ, hold)
        labeled_cats = {c: set(train[c].astype(str)) for c in s.categorical}

        order = self.cfg["methods_cost_order"]
        parent_window = self.model_row(champ_v)["train_window"]
        out = []
        for method in sorted(set(methods), key=order.index):
            if method == "recalibrate":
                model = champ.recalibrated(calib)
                tw = parent_window  # same trees, same reference data
                note = f"Refit calibration on {win['calib']}. Trees unchanged."
            elif method == "finetune":
                model = champ.finetuned(ft, calib, extra_iter=80, sample_weight=self._recency_weights(obj, ft, win["recent"]))
                tw = f"{win['finetune'][0]}..{win['finetune'][-1]}"
                note = (f"Warm start: {champ_v} plus 80 trees fitted on {', '.join(win['finetune'])}. "
                        "Encoder frozen, so new categories stay unknown.")
            elif method == "retrain":
                model = ScoringModel(s).fit(train, calib, self._recency_weights(obj, train, win["recent"]))
                tw = f"{win['train'][0]}..{win['train'][-1]}"
                learned = {c: sorted(v - set(champ.known_categories.get(c, []))) for c, v in labeled_cats.items()}
                learned = {c: v for c, v in learned.items() if v}
                note = f"Full retrain on {tw} with a {c['recency_half_life']}-period recency half-life."
                if learned:
                    note += " Learns new categories: " + "; ".join(f"{k}={', '.join(v)}" for k, v in learned.items()) + "."
            else:
                raise ValueError(f"unknown method {method}")
            metrics = {"holdout": self._evaluate(obj, model, hold), "champion_on_holdout": champ_metrics}
            v = self._register(obj, model, method, champ_v, win, metrics, self._importance(model, hold),
                               "challenger", notes=note, train_window=tw)
            out.append({"version": v, "method": method, "note": note, "metrics": metrics["holdout"]})
        self.wh.audit(actor, "build_challengers", obj, period, champ_v,
                      {"methods": [o["method"] for o in out], "versions": [o["version"] for o in out],
                       "holdout": win["holdout"]})
        return {"object": obj, "period": period, "champion": champ_v, "windows": win,
                "champion_metrics": champ_metrics, "challengers": out}

    # ================================================================== gates and promotion
    def _tier_churn(self, obj: str, period: str, champ: ScoringModel, chal: ScoringModel) -> float:
        cur = self.data(obj, [period])
        if cur.empty:
            return 0.0
        return float(np.mean(champ.tier(champ.score(cur)) != chal.tier(chal.score(cur))))

    def gate_check(self, obj: str, period: str, build: dict) -> dict:
        g = self.gcfg(obj)
        champ_v, champ = self.champion(obj)
        cm = build["champion_metrics"]
        champ_fail = []
        if cm["auc"] is not None and cm["auc"] < g["min_auc"]:
            champ_fail.append("AUC below floor")
        if cm["calibration_gap"] is not None and abs(cm["calibration_gap"]) > g["max_abs_calibration_gap"]:
            champ_fail.append("calibration off")
        if cm["top_decile_lift"] is not None and cm["top_decile_lift"] < g["min_top_decile_lift"]:
            champ_fail.append("lift below floor")

        results = []
        for ch in build["challengers"]:
            m = ch["metrics"]
            gain = m["auc"] - cm["auc"]
            checks = [
                {"gate": "auc_floor", "passed": m["auc"] >= g["min_auc"], "detail": f"AUC {m['auc']:.3f}, floor {g['min_auc']}"},
                {"gate": "beats_champion", "passed": gain >= g["min_auc_gain"] or (bool(champ_fail) and gain >= 0),
                 "detail": f"{gain:+.3f} AUC vs {champ_v}" + (f" (champion failing: {', '.join(champ_fail)})" if champ_fail else "")},
                {"gate": "brier", "passed": m["brier"] <= cm["brier"] + g["max_brier_increase"],
                 "detail": f"Brier {m['brier']:.4f} vs champion {cm['brier']:.4f}"},
                {"gate": "calibration", "passed": abs(m["calibration_gap"]) <= g["max_abs_calibration_gap"],
                 "detail": f"gap {m['calibration_gap'] * 100:+.1f} pts, limit {g['max_abs_calibration_gap'] * 100:.0f}"},
                {"gate": "top_decile_lift", "passed": m["top_decile_lift"] >= g["min_top_decile_lift"],
                 "detail": f"lift {m['top_decile_lift']:.2f}x, floor {g['min_top_decile_lift']}x"},
            ]
            segs = m.get("segments", {})
            worst = min(segs.items(), key=lambda kv: kv[1]) if segs else None
            checks.append({"gate": "segment_floor", "passed": all(v >= g["min_segment_auc"] for v in segs.values()),
                           "detail": f"worst {g['segment_by']} {worst[0]} AUC {worst[1]:.3f}" if worst else "no segment large enough"})
            churn = None
            if g.get("max_tier_churn") is not None:
                churn = self._tier_churn(obj, period, champ, self.load(ch["version"]))
                checks.append({"gate": "tier_stability", "passed": churn <= g["max_tier_churn"],
                               "detail": f"{churn:.0%} of records change tier, limit {g['max_tier_churn']:.0%}"})
            passed = all(c["passed"] for c in checks)
            cur = self.data(obj, [period])
            unknown = self.load(ch["version"]).unseen_categories(cur) if len(cur) else {}
            unknown_share = round(sum(sum(v.values()) for v in unknown.values()), 4)
            results.append({**ch, "gates": checks, "passed": passed, "tier_churn": churn,
                            "unknown_category_share": unknown_share})
            self._update(ch["version"], gates=checks)

        eligible = [r for r in results if r["passed"]]
        chosen, reason = None, ""
        if eligible:
            best = max(r["metrics"]["auc"] for r in eligible)
            order = self.cfg["methods_cost_order"]
            near = [r for r in eligible if r["metrics"]["auc"] >= best - g["prefer_cheaper_within_auc"]]
            limit = self.cfg["monitor"]["unseen_share_action"]
            # Prefer a model that knows today's population, then the cheapest update.
            chosen = sorted(near, key=lambda r: (r["unknown_category_share"] > limit, order.index(r["method"])))[0]
            reason = (f"{chosen['version']} ({chosen['method']}) passed all gates. AUC {chosen['metrics']['auc']:.3f} "
                      f"vs champion {cm['auc']:.3f} on {build['windows']['holdout']}.")
            if len(near) > 1:
                cheaper = [r for r in near if order.index(r["method"]) < order.index(chosen["method"])]
                if cheaper:
                    reason += (f" Chosen over cheaper {', '.join(r['method'] for r in cheaper)} because it knows "
                               f"categories that cover {1 - chosen['unknown_category_share']:.0%} of current records.")
                else:
                    reason += " Chosen as the cheapest update within tolerance of the best."
        else:
            fails = {r["version"]: [c["gate"] for c in r["gates"] if not c["passed"]] for r in results}
            reason = "No challenger passed every gate. Champion holds. " + "; ".join(
                f"{v} failed {', '.join(f)}" for v, f in fails.items())
        return {"object": obj, "period": period, "champion": champ_v, "champion_metrics": cm,
                "champion_failing": champ_fail, "candidates": results,
                "chosen": chosen["version"] if chosen else None, "reason": reason,
                "requires_approval": bool(chosen) and bool(g["require_human_approval"])}

    def promote(self, obj: str, version: str, approved_by: str, period: str = "", reason: str = "",
                actor: str = "governance-agent") -> dict:
        old = self.champion_version(obj)
        if old == version:
            return {"promoted": False, "reason": f"{version} is already champion"}
        if old:
            self._update(old, status="retired", retired_at=now())
        self._update(version, status="champion", approved_by=approved_by, promoted_at=now(), notes=reason or "")
        self.wh.audit(actor, "promote", obj, period, version, {"previous": old, "approved_by": approved_by, "reason": reason})
        return {"promoted": True, "champion": version, "previous": old, "approved_by": approved_by}

    def decide(self, obj: str, period: str, gate_result: dict, approve: bool = False,
               approver: str = "", actor: str = "governance-agent") -> dict:
        chosen = gate_result["chosen"]
        for c in gate_result["candidates"]:
            if c["version"] != chosen:
                self._update(c["version"], status="rejected")
        if not chosen:
            self.wh.audit(actor, "hold", obj, period, gate_result["champion"], {"reason": gate_result["reason"]})
            return {"action": "hold", "champion": gate_result["champion"], "reason": gate_result["reason"]}
        if gate_result["requires_approval"] and not approve:
            self._update(chosen, status="pending_approval", notes=gate_result["reason"])
            self.wh.audit(actor, "request_approval", obj, period, chosen, {"reason": gate_result["reason"]})
            return {"action": "pending_approval", "champion": gate_result["champion"], "candidate": chosen,
                    "reason": gate_result["reason"] + " Waiting for RevOps approval."}
        who = approver or ("governance-agent (auto, gates passed)" if not gate_result["requires_approval"] else "RevOps")
        res = self.promote(obj, chosen, who, period, gate_result["reason"], actor)
        return {"action": "promote", **res, "reason": gate_result["reason"]}

    def approve(self, version: str, approver: str) -> dict:
        row = self.model_row(version)
        if row["status"] != "pending_approval":
            return {"promoted": False, "reason": f"{version} is {row['status']}, not pending approval"}
        reason = (row.get("notes") or "").strip()
        reason = (reason + " " if reason else "") + f"Approved by {approver}."
        return self.promote(row["object"], version, approver, reason=reason, actor="human")

    def rollback(self, obj: str, reason: str = "", actor: str = "governance-agent") -> dict:
        reg = self.registry(obj)
        retired = reg[(reg["status"] == "retired") & (reg["promoted_at"] != "")]
        if retired.empty:
            return {"rolled_back": False, "reason": "no previous champion to roll back to"}
        prev = retired.sort_values("retired_at").iloc[-1]["version"]
        cur = self.champion_version(obj)
        self._update(cur, status="rolled_back", retired_at=now())
        self._update(prev, status="champion", promoted_at=now(), notes=f"Restored by rollback. {reason}")
        self.wh.audit(actor, "rollback", obj, "", prev, {"from": cur, "reason": reason})
        return {"rolled_back": True, "champion": prev, "previous": cur}

    # ================================================================== scoring and write-back
    def score(self, obj: str, period: str, write_back: bool = True, dry_run: bool = False,
              actor: str = "scoring-agent") -> dict:
        s = spec_for(obj)
        v, model = self.champion(obj)
        cur = self.data(obj, [period])
        if cur.empty:
            return {"scored": 0, "period": period}
        scores = model.score(cur)
        out = pd.DataFrame({"object": obj, "record_id": cur[s.id_col], "period": period, "model_version": v,
                            "score": scores, "tier": model.tier(scores), "reasons": model.explain(cur),
                            "scored_at": now()})
        if not dry_run:
            self.wh.write("SCORES", out)
        crm_result = self.crm.write_scores(obj, out, dry_run=dry_run) if write_back else {"skipped": True}
        tiers = out["tier"].value_counts().reindex(["A", "B", "C", "D"], fill_value=0).to_dict()
        summary = {"object": obj, "period": period, "model_version": v, "scored": len(out),
                   "tiers": {k: int(n) for k, n in tiers.items()}, "mean_score": round(float(scores.mean()), 1),
                   "crm": crm_result}
        self.wh.audit(actor, "score_and_write_back", obj, period, v, summary)
        return summary

    def explain_record(self, obj: str, record_id: str) -> dict:
        s = spec_for(obj)
        df = self.data(obj)
        rec = df[df[s.id_col] == record_id]
        if rec.empty:
            return {"error": f"no {obj} {record_id}"}
        rec = rec.sort_values("period").tail(1)
        v, model = self.champion(obj)
        score = float(model.score(rec)[0])
        contrib = model.contributions(rec).iloc[0].sort_values(ascending=False)
        return {"object": obj, "record_id": record_id, "name": rec[s.name_col].iat[0], "period": rec["period"].iat[0],
                "model_version": v, "score": score, "tier": str(model.tier([score])[0]),
                "reasons": model.explain(rec)[0],
                "contributions_pts": {s.labels.get(k, k): round(float(val * 100), 1) for k, val in contrib.items()}}

    def log_cycle(self, obj: str, period: str, record: dict) -> None:
        self.wh.write("CYCLE_LOG", pd.DataFrame([{"object": obj, "period": period,
                                                   "record": json.dumps(record, default=str), "created_at": now()}]))

    def cycles(self, obj: str | None = None) -> list[dict]:
        df = self.wh.query("SELECT * FROM CYCLE_LOG" + (" WHERE object = ?" if obj else "") + " ORDER BY created_at",
                           [obj] if obj else None)
        return [json.loads(r) for r in df["record"]]

    def model_card(self, version: str) -> str:
        r = self.model_row(version)
        h = r["metrics"].get("holdout", {})
        lines = [
            f"# Model card: {version}", "",
            f"- Object: {r['object']}", f"- Status: {r['status']}", f"- Method: {r['method']}",
            f"- Parent: {r['parent_version'] or 'none'}", f"- Training window: {r['train_window']}",
            f"- Calibration period: {r['calib_period']}", f"- Out-of-time holdout: {r['holdout_period']}",
            f"- Approved by: {r['approved_by'] or 'not promoted'}", f"- Promoted at: {r['promoted_at'] or 'n/a'}",
            f"- Notes: {r['notes']}",
            f"- Runtime: Python {r['metrics'].get('runtime', {}).get('python', '?')}, "
            f"scikit-learn {r['metrics'].get('runtime', {}).get('scikit_learn', '?')}",
            "", "## Holdout metrics", "",
            f"| AUC | Brier | Calibration gap | Top-decile lift | Records | Positives |",
            f"| --- | --- | --- | --- | --- | --- |",
            f"| {h.get('auc')} | {h.get('brier')} | {h.get('calibration_gap')} | {h.get('top_decile_lift')} | {h.get('n')} | {h.get('positives')} |",
            "", "## Segment AUC", "",
        ]
        for seg, auc in (h.get("segments") or {}).items():
            lines.append(f"- {seg}: {auc}")
        lines += ["", "## Feature importance (share of mean absolute contribution)", ""]
        for f, w in list(r["importance"].items())[:10]:
            lines.append(f"- {f}: {w:.1%}")
        if r["gates"]:
            lines += ["", "## Promotion gates", "", "| Gate | Passed | Detail |", "| --- | --- | --- |"]
            for gte in r["gates"]:
                lines.append(f"| {gte['gate']} | {'yes' if gte['passed'] else 'no'} | {gte['detail']} |")
        return "\n".join(lines)
