"""Drift and performance measurement.

Two kinds of drift, two clocks:

* Input drift (PSI) is known the day new records land. No labels needed.
* Performance drift (AUC, calibration, lift) waits for outcomes. Leads wait
  30 days. Accounts wait a quarter.

Watching inputs is how the monitor sees trouble a full period before the
labels confirm it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from .features import FeatureSpec

_EPS = 1e-4


def psi_numeric(ref: pd.Series, cur: pd.Series, bins: int = 10) -> float:
    ref = ref.astype(float).dropna().to_numpy()
    cur = cur.astype(float).dropna().to_numpy()
    if len(ref) == 0 or len(cur) == 0:
        return 0.0
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    p = np.histogram(ref, edges)[0] / len(ref)
    q = np.histogram(cur, edges)[0] / len(cur)
    p, q = np.clip(p, _EPS, None), np.clip(q, _EPS, None)
    return float(np.sum((q - p) * np.log(q / p)))


def psi_categorical(ref: pd.Series, cur: pd.Series) -> float:
    ref = ref.astype(str)
    cur = cur.astype(str)
    cats = sorted(set(ref.unique()) | set(cur.unique()))
    p = ref.value_counts(normalize=True).reindex(cats, fill_value=0).to_numpy()
    q = cur.value_counts(normalize=True).reindex(cats, fill_value=0).to_numpy()
    p, q = np.clip(p, _EPS, None), np.clip(q, _EPS, None)
    return float(np.sum((q - p) * np.log(q / p)))


def feature_drift(ref: pd.DataFrame, cur: pd.DataFrame, spec: FeatureSpec) -> pd.DataFrame:
    rows = []
    for f in spec.numeric:
        rows.append({"feature": f, "kind": "numeric", "psi": psi_numeric(ref[f], cur[f]),
                     "ref_mean": float(ref[f].mean()), "cur_mean": float(cur[f].mean())})
    for f in spec.categorical:
        known = set(ref[f].astype(str).unique())
        unseen = cur[f].astype(str)[~cur[f].astype(str).isin(known)]
        rows.append({"feature": f, "kind": "categorical", "psi": psi_categorical(ref[f], cur[f]),
                     "unseen_share": round(len(unseen) / max(len(cur), 1), 4),
                     "unseen_values": sorted(unseen.unique().tolist())})
    out = pd.DataFrame(rows)
    out["psi"] = out["psi"].round(4)
    return out.sort_values("psi", ascending=False).reset_index(drop=True)


def psi_band(psi: float, watch: float = 0.10, action: float = 0.25) -> str:
    return "action" if psi >= action else "watch" if psi >= watch else "stable"


def performance(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y).astype(int)
    p = np.asarray(p, dtype=float)
    n, pos = len(y), int(y.sum())
    out = {"n": n, "positives": pos, "base_rate": round(pos / n, 4) if n else None}
    if n == 0 or pos == 0 or pos == n:
        return {**out, "auc": None, "brier": None, "calibration_gap": None, "ece": None, "top_decile_lift": None}
    order = np.argsort(-p)
    top = order[: max(1, n // 10)]
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = sum(abs(p[bins == b].mean() - y[bins == b].mean()) * (bins == b).mean() for b in range(10) if (bins == b).any())
    out.update({
        "auc": round(float(roc_auc_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "calibration_gap": round(float(p.mean() - y.mean()), 4),  # + means scores run hot
        "ece": round(float(ece), 4),
        "top_decile_lift": round(float(y[top].mean() / y.mean()), 2),
    })
    return out


def segment_auc(df: pd.DataFrame, y_col: str, p: np.ndarray, by: str, min_rows: int, min_pos: int) -> dict:
    out = {}
    tmp = df[[by, y_col]].copy()
    tmp["_p"] = p
    for seg, g in tmp.groupby(by):
        yy = g[y_col].astype(int)
        if len(g) >= min_rows and yy.sum() >= min_pos and yy.sum() < len(g):
            out[str(seg)] = round(float(roc_auc_score(yy, g["_p"])), 4)
    return out
