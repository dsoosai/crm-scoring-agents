"""The scoring model and its three update paths.

ScoringModel = ordinal encoder + gradient boosted trees + Platt calibration +
tier cutoffs. It supports the three ways an agent can update a model, from
cheapest to most expensive:

1. recalibrate   Refit only the calibration layer on recent labels. Fixes
                 scores that rank well but read too high or too low.
2. finetune      Warm-start: keep the champion's trees and add trees fitted on
                 the most recent labeled data. Adapts to a changed relationship
                 without forgetting everything. Cannot learn a category it has
                 never seen, because the encoder is frozen.
3. retrain       New encoder, new trees, rolling window with recency weights.
                 The only path that learns new categories.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OrdinalEncoder

from .features import FeatureSpec

DEFAULT_PARAMS = {
    "max_iter": 250,
    "learning_rate": 0.05,
    "max_leaf_nodes": 15,
    "min_samples_leaf": 40,
    "l2_regularization": 1.0,
    "random_state": 7,
}
TIER_SHARES = {"A": 0.15, "B": 0.25, "C": 0.30}  # D is the rest
_EPS = 1e-6


@dataclass
class Explanation:
    reasons: str
    contributions: dict


class ScoringModel:
    def __init__(self, spec: FeatureSpec, params: dict | None = None):
        self.spec = spec
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.encoder: OrdinalEncoder | None = None
        self.clf: HistGradientBoostingClassifier | None = None
        self.calibrator: LogisticRegression | None = None
        self.cutoffs: dict[str, float] = {}
        self.reference: dict[str, object] = {}
        self.known_categories: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ encoding
    def _X(self, df: pd.DataFrame) -> np.ndarray:
        num = df[list(self.spec.numeric)].astype(float).to_numpy()
        cat = self.encoder.transform(df[list(self.spec.categorical)].astype(str))
        return np.hstack([num, cat])

    def _y(self, df: pd.DataFrame) -> np.ndarray:
        return df[self.spec.label].astype(int).to_numpy()

    # ------------------------------------------------------------------ fitting
    def fit(self, train: pd.DataFrame, calib: pd.DataFrame, sample_weight: np.ndarray | None = None) -> "ScoringModel":
        cats = list(self.spec.categorical)
        self.encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan, dtype=float)
        self.encoder.fit(train[cats].astype(str))
        self.known_categories = {c: [str(v) for v in vals] for c, vals in zip(cats, self.encoder.categories_)}
        mask = [False] * len(self.spec.numeric) + [True] * len(cats)
        self.clf = HistGradientBoostingClassifier(categorical_features=mask, early_stopping=False, **self.params)
        self.clf.fit(self._X(train), self._y(train), sample_weight=sample_weight)
        self.reference = {c: float(train[c].median()) for c in self.spec.numeric}
        self.reference.update({c: str(train[c].astype(str).mode().iat[0]) for c in cats})
        self._calibrate(calib)
        return self

    def _raw_logit(self, df: pd.DataFrame) -> np.ndarray:
        p = np.clip(self.clf.predict_proba(self._X(df))[:, 1], _EPS, 1 - _EPS)
        return np.log(p / (1 - p))

    def _calibrate(self, calib: pd.DataFrame) -> None:
        self.calibrator = LogisticRegression(C=1e4, max_iter=1000)
        self.calibrator.fit(self._raw_logit(calib).reshape(-1, 1), self._y(calib))
        scores = self.score(calib)
        a = TIER_SHARES["A"]
        b = a + TIER_SHARES["B"]
        c = b + TIER_SHARES["C"]
        self.cutoffs = {
            "A": float(np.quantile(scores, 1 - a)),
            "B": float(np.quantile(scores, 1 - b)),
            "C": float(np.quantile(scores, 1 - c)),
        }

    # ------------------------------------------------------------------ update paths
    def recalibrated(self, calib: pd.DataFrame) -> "ScoringModel":
        m = copy.deepcopy(self)
        m._calibrate(calib)
        return m

    def finetuned(self, recent: pd.DataFrame, calib: pd.DataFrame, extra_iter: int = 80,
                  sample_weight: np.ndarray | None = None) -> "ScoringModel":
        m = copy.deepcopy(self)
        m.clf.set_params(warm_start=True, max_iter=m.clf.n_iter_ + extra_iter)
        m.clf.fit(m._X(recent), m._y(recent), sample_weight=sample_weight)
        m.clf.set_params(warm_start=False)
        m._calibrate(calib)
        return m

    # ------------------------------------------------------------------ scoring
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return self.calibrator.predict_proba(self._raw_logit(df).reshape(-1, 1))[:, 1]

    def score(self, df: pd.DataFrame) -> np.ndarray:
        """0 to 100. Reads as the calibrated chance of the outcome, in percent."""
        return np.round(self.predict_proba(df) * 100, 1)

    def tier(self, scores: np.ndarray) -> np.ndarray:
        s = np.asarray(scores)
        return np.select([s >= self.cutoffs["A"], s >= self.cutoffs["B"], s >= self.cutoffs["C"]],
                         ["A", "B", "C"], default="D")

    def unseen_categories(self, df: pd.DataFrame) -> dict[str, dict[str, float]]:
        out = {}
        for c in self.spec.categorical:
            vals = df[c].astype(str)
            mask = ~vals.isin(self.known_categories.get(c, []))
            if mask.any():
                out[c] = {k: round(float(v), 4) for k, v in vals[mask].value_counts(normalize=False).div(len(df)).items()}
        return out

    # ------------------------------------------------------------------ explanations
    def contributions(self, df: pd.DataFrame) -> pd.DataFrame:
        """Change in probability when each feature is reset to its training reference.

        Positive means the feature lifted this record's score. Cheap, model-agnostic,
        and easy to say to a sales rep.
        """
        base = self.predict_proba(df)
        out = {}
        for f in self.spec.features:
            tmp = df.copy()
            tmp[f] = self.reference[f]
            out[f] = base - self.predict_proba(tmp)
        return pd.DataFrame(out, index=df.index)

    def explain(self, df: pd.DataFrame, top_k: int = 3) -> list[str]:
        contrib = self.contributions(df)
        labels = self.spec.labels
        reasons = []
        for i, (_, row) in enumerate(contrib.iterrows()):
            top = row.sort_values(ascending=False).head(top_k)
            parts = []
            for f, d in top.items():
                if d <= 0.005:
                    continue
                v = df.iloc[i][f]
                v = f"{v:,.0f}" if isinstance(v, (int, float, np.integer, np.floating)) else str(v)
                parts.append(f"{labels.get(f, f)} {v} (+{d * 100:.0f})")
            reasons.append("; ".join(parts)[:255] or "No single factor stands out")
        return reasons

    def global_importance(self, df: pd.DataFrame) -> dict[str, float]:
        contrib = self.contributions(df).abs().mean()
        total = contrib.sum() or 1.0
        return {k: round(float(v / total), 4) for k, v in contrib.sort_values(ascending=False).items()}
