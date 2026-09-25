"""Render the lifecycle dashboard as one static HTML page (space/index.html).

The same file is the Hugging Face Space. No build step, no server.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .agents.a2a import to_jsonable
from .features import spec_for
from .service import build_lifecycle

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "dashboard_template.html"


def _object_payload(lc, obj: str) -> dict:
    s = spec_for(obj)
    # One record per period: a re-run of a period replaces the earlier record.
    cycles = sorted({c["period"]: c for c in lc.cycles(obj)}.values(), key=lambda c: c["period"])
    # Drift as the monitor saw it inside each cycle (ad hoc MCP checks do not rewrite history).
    psi = {c["period"]: {d["feature"]: d["psi"] for d in c["feature_drift"]} for c in cycles}
    periods = [c["period"] for c in cycles]
    feats = sorted(s.features, key=lambda f: -max((psi.get(p, {}).get(f, 0) for p in periods), default=0))[:5]

    quality = []
    for c in cycles:
        quality.append({"period": c["monitor"]["labels_through"],
                        "managed": c["champion_perf"].get("auc"),
                        "frozen": c["monitor"]["frozen_v1_auc"],
                        "rules": c["monitor"]["rules_v0_auc"],
                        "champion": c["champion_before"]})
    promotions = [{"cycle": c["period"], "version": c["decision"]["champion"],
                   "method": next((ch["method"] for ch in c["challengers"] if ch["version"] == c["decision"]["champion"]), "")}
                  for c in cycles if c["decision"]["action"] == "promote"]
    timeline = [{
        "period": c["period"], "status": c["monitor"]["status"], "findings": c["monitor"]["findings"],
        "plan": c["plan"]["why"], "challengers": c["challengers"], "decision": c["decision"]["action"],
        "champion": c["decision"].get("champion"), "reason": c["decision"].get("reason", ""),
        "summary": c["summary"], "scored": c["scoring"]["scored"], "tiers": c["scoring"]["tiers"],
    } for c in cycles]
    reg = lc.registry(obj)
    registry = [{
        "version": r["version"], "status": r["status"], "method": r["method"], "train_window": r["train_window"],
        "holdout": r["holdout_period"], "auc": json.loads(r["metrics"]).get("holdout", {}).get("auc"),
        "approved_by": r["approved_by"], "notes": r["notes"],
    } for _, r in reg.iterrows()]
    last = cycles[-1] if cycles else {}
    return {
        "label": "Lead conversion (30 days)" if obj == "lead" else "Account expansion (next quarter)",
        "cadence": lc.ocfg(obj)["cadence"], "quality": quality, "promotions": promotions,
        "drift": {"periods": periods, "features": [{"key": f, "label": s.labels.get(f, f)} for f in feats],
                  "values": [[psi.get(p, {}).get(f) for p in periods] for f in feats]},
        "timeline": timeline, "registry": registry,
        "champion": lc.champion_version(obj),
        "last": {"managed": quality[-1]["managed"] if quality else None,
                 "frozen": quality[-1]["frozen"] if quality else None,
                 "rules": quality[-1]["rules"] if quality else None,
                 "period": last.get("period")},
        "counts": {"cycles": len(cycles), "promotions": len(promotions),
                   "holds": sum(1 for c in cycles if c["decision"]["action"] == "hold")},
    }


def render(workdir: str = "demo_run", out: str | None = None) -> str:
    lc = build_lifecycle(workdir=workdir)
    payload = {"objects": {o: _object_payload(lc, o) for o in ("lead", "account") if lc.cycles(o)}}
    html = TEMPLATE.read_text().replace("__DATA__", json.dumps(to_jsonable(payload)))
    out = Path(out or ROOT / "space" / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return str(out)


if __name__ == "__main__":
    print(render(os.getenv("CRM_WORKDIR", "demo_run")))
