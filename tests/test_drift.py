import numpy as np
import pandas as pd

from crmscore.drift import feature_drift, performance, psi_categorical, psi_numeric
from crmscore.features import LEAD


def test_psi_zero_for_same_distribution():
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(size=5000))
    assert psi_numeric(a, a) < 1e-9


def test_psi_flags_a_shift():
    rng = np.random.default_rng(0)
    ref = pd.Series(rng.normal(size=5000))
    cur = pd.Series(rng.normal(loc=1.0, size=5000))
    assert psi_numeric(ref, cur) > 0.25


def test_psi_counts_unseen_categories():
    ref = pd.Series(["CRM"] * 50 + ["ERP"] * 50)
    cur = pd.Series(["CRM"] * 40 + ["ERP"] * 40 + ["AI Agents"] * 20)
    assert psi_categorical(ref, cur) > 0.25


def test_feature_drift_reports_unseen_values():
    ref = pd.DataFrame({f: [1] * 10 for f in LEAD.numeric} | {c: ["x"] * 10 for c in LEAD.categorical})
    cur = ref.copy()
    cur.loc[:4, "keyword"] = "AI Agents"
    out = feature_drift(ref, cur, LEAD)
    row = out[out["feature"] == "keyword"].iloc[0]
    assert row["unseen_values"] == ["AI Agents"]
    assert row["unseen_share"] == 0.5


def test_performance_metrics():
    y = np.array([0, 0, 0, 1, 1, 0, 1, 0, 0, 1])
    p = np.array([0.1, 0.2, 0.1, 0.9, 0.8, 0.3, 0.7, 0.2, 0.1, 0.6])
    m = performance(y, p)
    assert m["auc"] == 1.0
    assert m["top_decile_lift"] == 2.5
