"""v0 rule-based scores, ported from the original notebooks.

These are the "before" picture. They use hand-set weights and never see an
outcome, so they cannot learn and cannot tell you when they are wrong.

A finding worth saying out loud: in both notebooks every one-hot category gets
the same weight. Each record has exactly one active category per group, so the
category terms add the same constant to every record. Industry, department,
role and keyword never move a v0 score. The lead score is effectively
0.30 + 0.20 * site_visits / max(site_visits).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def account_score_v0(df: pd.DataFrame) -> np.ndarray:
    """CustomerAccountScoring.ipynb, extended score (weight-normalized version)."""
    def minmax(s: pd.Series) -> pd.Series:
        rng = s.max() - s.min()
        return (s - s.min()) / rng if rng else s * 0.0

    core = {"sales": 0.25, "revenue": 0.25, "profit": 0.25}
    score = sum(minmax(df[c]) * w for c, w in core.items())
    score = score + 0.10 * (df["transactions"] / df["transactions"].max())
    # Active industry and department each carry one fixed weight. Constant per row.
    score = score + 0.10 * pd.get_dummies(df["industry"]).sum(axis=1)
    score = score + 0.05 * pd.get_dummies(df["department"]).sum(axis=1)
    return score.to_numpy(dtype=float)


def lead_score_v0(df: pd.DataFrame) -> np.ndarray:
    """LeadScoring.ipynb weighted sum."""
    score = 0.2 * (df["site_visits"] / max(df["site_visits"].max(), 1))
    score = score + 0.10 * pd.get_dummies(df["industry"]).sum(axis=1)
    score = score + 0.15 * pd.get_dummies(df["role"]).sum(axis=1)
    score = score + 0.05 * pd.get_dummies(df["keyword"]).sum(axis=1)
    return score.to_numpy(dtype=float)


def score_v0(obj: str, df: pd.DataFrame) -> np.ndarray:
    return account_score_v0(df) if obj == "account" else lead_score_v0(df)
