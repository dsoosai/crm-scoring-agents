"""CRM write-back. A mock org locally, a Salesforce org in live mode.

Custom fields (deployed from salesforce/force-app):
  Account: CRM_Score_Ext_Id__c, Account_Score__c, Account_Tier__c,
           Score_Model_Version__c, Score_Reasons__c, Score_Updated__c
  Lead:    CRM_Score_Ext_Id__c, Lead_Score__c, Lead_Grade__c,
           Score_Model_Version__c, Score_Reasons__c, Score_Updated__c

Salesforce writes are update-only. The agent never creates records in the
org; it only updates records that already carry an external id. A scoring job
that can create records can also flood a Developer Edition org's storage.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

SF_OBJECT = {"account": "Account", "lead": "Lead"}
SCORE_FIELD = {"account": "Account_Score__c", "lead": "Lead_Score__c"}
TIER_FIELD = {"account": "Account_Tier__c", "lead": "Lead_Grade__c"}
EXT_ID = "CRM_Score_Ext_Id__c"


def _payload(obj: str, scores: pd.DataFrame) -> list[dict]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{
        EXT_ID: r.record_id,
        SCORE_FIELD[obj]: float(r.score),
        TIER_FIELD[obj]: r.tier,
        "Score_Model_Version__c": r.model_version,
        "Score_Reasons__c": (r.reasons or "")[:255],
        "Score_Updated__c": ts,
    } for r in scores.itertuples()]


class MockCRM:
    """A stand-in org kept in its own DuckDB file, so it behaves like a separate system."""

    name = "mock"

    def __init__(self, path: str = "mock_org.duckdb"):
        import duckdb
        self.con = duckdb.connect(path)
        for obj in SF_OBJECT.values():
            self.con.execute(
                f"""CREATE TABLE IF NOT EXISTS {obj} ({EXT_ID} VARCHAR PRIMARY KEY, Name VARCHAR,
                    Score DOUBLE, Tier VARCHAR, Score_Model_Version__c VARCHAR,
                    Score_Reasons__c VARCHAR, Score_Updated__c VARCHAR)""")

    def seed(self, obj: str, records: pd.DataFrame, id_col: str, name_col: str) -> int:
        df = pd.DataFrame({EXT_ID: records[id_col], "Name": records[name_col]}).drop_duplicates(EXT_ID)
        self.con.register("_seed", df)
        self.con.execute(f"""INSERT INTO {SF_OBJECT[obj]} ({EXT_ID}, Name)
                             SELECT {EXT_ID}, Name FROM _seed
                             WHERE {EXT_ID} NOT IN (SELECT {EXT_ID} FROM {SF_OBJECT[obj]})""")
        self.con.unregister("_seed")
        return len(df)

    def write_scores(self, obj: str, scores: pd.DataFrame, dry_run: bool = False) -> dict:
        rows = _payload(obj, scores)
        if dry_run or not rows:
            return {"crm": self.name, "object": SF_OBJECT[obj], "would_update": len(rows), "dry_run": True}
        df = pd.DataFrame(rows).rename(columns={SCORE_FIELD[obj]: "Score", TIER_FIELD[obj]: "Tier"})
        self.con.register("_upd", df)
        before = self.con.execute(f"SELECT COUNT(*) FROM {SF_OBJECT[obj]}").fetchone()[0]
        self.con.execute(f"""
            INSERT INTO {SF_OBJECT[obj]} ({EXT_ID}, Score, Tier, Score_Model_Version__c, Score_Reasons__c, Score_Updated__c)
            SELECT {EXT_ID}, Score, Tier, Score_Model_Version__c, Score_Reasons__c, Score_Updated__c FROM _upd
            ON CONFLICT ({EXT_ID}) DO UPDATE SET Score = excluded.Score, Tier = excluded.Tier,
                Score_Model_Version__c = excluded.Score_Model_Version__c,
                Score_Reasons__c = excluded.Score_Reasons__c, Score_Updated__c = excluded.Score_Updated__c""")
        after = self.con.execute(f"SELECT COUNT(*) FROM {SF_OBJECT[obj]}").fetchone()[0]
        self.con.unregister("_upd")
        return {"crm": self.name, "object": SF_OBJECT[obj], "updated": len(rows) - (after - before),
                "created": after - before, "dry_run": False}

    def get(self, obj: str, record_id: str) -> dict | None:
        df = self.con.execute(f"SELECT * FROM {SF_OBJECT[obj]} WHERE {EXT_ID} = ?", [record_id]).fetchdf()
        return None if df.empty else df.iloc[0].to_dict()


class SalesforceCRM:
    """Live mode via simple-salesforce.

    Auth, in order of preference:
      SF_CONSUMER_KEY + SF_PRIVATE_KEY_FILE + SF_USERNAME   (JWT bearer, External Client App)
      SF_USERNAME + SF_PASSWORD + SF_SECURITY_TOKEN          (quick start for a Developer Edition org)
    SF_DOMAIN defaults to "login". Use "test" for a sandbox.
    """

    name = "salesforce"

    def __init__(self):
        from simple_salesforce import Salesforce
        domain = os.getenv("SF_DOMAIN", "login")
        if os.getenv("SF_CONSUMER_KEY") and os.getenv("SF_PRIVATE_KEY_FILE"):
            self.sf = Salesforce(username=os.environ["SF_USERNAME"], consumer_key=os.environ["SF_CONSUMER_KEY"],
                                 privatekey_file=os.environ["SF_PRIVATE_KEY_FILE"], domain=domain)
        else:
            self.sf = Salesforce(username=os.environ["SF_USERNAME"], password=os.environ["SF_PASSWORD"],
                                 security_token=os.getenv("SF_SECURITY_TOKEN", ""), domain=domain)

    def _existing_ids(self, obj: str) -> dict[str, str]:
        soql = f"SELECT Id, {EXT_ID} FROM {SF_OBJECT[obj]} WHERE {EXT_ID} != null"
        recs = self.sf.query_all(soql)["records"]
        return {r[EXT_ID]: r["Id"] for r in recs}

    def seed(self, obj: str, records: pd.DataFrame, id_col: str, name_col: str) -> int:
        """Insert a small sample of records so there is something to score. Run once."""
        existing = self._existing_ids(obj)
        todo = records[~records[id_col].isin(existing)]
        if obj == "account":
            rows = [{"Name": r[name_col], EXT_ID: r[id_col]} for _, r in todo.iterrows()]
        else:
            rows = [{"LastName": r["contact"], "Company": r[name_col], EXT_ID: r[id_col]} for _, r in todo.iterrows()]
        if rows:
            getattr(self.sf.bulk, SF_OBJECT[obj]).insert(rows, batch_size=5000)
        return len(rows)

    def write_scores(self, obj: str, scores: pd.DataFrame, dry_run: bool = False) -> dict:
        existing = self._existing_ids(obj)
        rows = []
        for row in _payload(obj, scores):
            sf_id = existing.get(row[EXT_ID])
            if sf_id:
                row = {k: v for k, v in row.items() if k != EXT_ID}
                row["Id"] = sf_id
                rows.append(row)
        skipped = len(scores) - len(rows)
        if dry_run or not rows:
            return {"crm": self.name, "object": SF_OBJECT[obj], "would_update": len(rows),
                    "skipped_not_in_org": skipped, "dry_run": True}
        results = getattr(self.sf.bulk, SF_OBJECT[obj]).update(rows, batch_size=5000)
        failed = [r for r in results if not r.get("success")]
        return {"crm": self.name, "object": SF_OBJECT[obj], "updated": len(rows) - len(failed),
                "failed": len(failed), "skipped_not_in_org": skipped, "dry_run": False,
                "first_error": failed[0].get("errors") if failed else None}

    def get(self, obj: str, record_id: str) -> dict | None:
        fields = f"Id, {SCORE_FIELD[obj]}, {TIER_FIELD[obj]}, Score_Model_Version__c, Score_Reasons__c, Score_Updated__c"
        safe_id = record_id.replace("\\", "\\\\").replace("'", "\\'")
        res = self.sf.query(f"SELECT {fields} FROM {SF_OBJECT[obj]} WHERE {EXT_ID} = '{safe_id}' LIMIT 1")
        return res["records"][0] if res["records"] else None


def get_crm(kind: str | None = None, path: str | None = None):
    kind = (kind or os.getenv("CRM_TARGET", "mock")).lower()
    if kind == "salesforce":
        return SalesforceCRM()
    return MockCRM(path or os.getenv("CRM_MOCK_PATH", "mock_org.duckdb"))
