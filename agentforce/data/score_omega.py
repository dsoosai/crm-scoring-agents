"""Score Omega Inc. with the champion account model from a replay, so the Agentforce demo
uses a real model output rather than a made-up tier.

    python agentforce/data/score_omega.py demo_run/warehouse.duckdb
prints the Salesforce score fields as JSON (pass that JSON to generate_demo_data.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from crmscore.lifecycle import _load_model
from crmscore.warehouse import DuckDBWarehouse


def main(db_path: str) -> dict:
    wh = DuckDBWarehouse(db_path)
    reg = wh.query("SELECT version, artifact FROM MODEL_REGISTRY WHERE object = 'account' AND status = 'champion'")
    version, blob = reg.iloc[0]["version"], reg.iloc[0]["artifact"]
    model = _load_model(blob)
    feats = json.loads((Path(__file__).resolve().parent / "out" / "omega_features.json").read_text())
    df = pd.DataFrame([feats])
    score = float(model.score(df)[0])
    tier = str(model.tier(model.score(df))[0])
    reasons = model.explain(df, top_k=3)[0]
    return {"Account_Score__c": round(score, 1), "Account_Tier__c": tier, "Score_Model_Version__c": version,
            "Score_Reasons__c": reasons[:255], "Score_Updated__c": "now"}


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1] if len(sys.argv) > 1 else "demo_run/warehouse.duckdb")))
