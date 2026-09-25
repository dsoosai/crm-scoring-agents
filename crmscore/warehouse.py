"""Warehouse backends. DuckDB locally, Snowflake in live mode. Same interface.

Tables (created on first use):
  ACCOUNT_SNAPSHOTS  quarterly account features and expansion outcome
  LEADS              monthly lead features and 30-day conversion outcome
  SCORES             every score written, with model version and reasons
  MODEL_REGISTRY     every model version, its metrics, gates and status
  DRIFT_REPORTS      one row per monitor run
  CYCLE_LOG          one row per lifecycle cycle, for the dashboard
  AUDIT_LOG          every agent action, who did it and why
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd

DATA_TABLES = {"account": "ACCOUNT_SNAPSHOTS", "lead": "LEADS"}

_DDL = {
    "SCORES": """object VARCHAR, record_id VARCHAR, period VARCHAR, model_version VARCHAR,
                 score DOUBLE, tier VARCHAR, reasons VARCHAR, scored_at VARCHAR""",
    "MODEL_REGISTRY": """version VARCHAR, object VARCHAR, status VARCHAR, method VARCHAR,
                 parent_version VARCHAR, created_at VARCHAR, train_window VARCHAR, calib_period VARCHAR,
                 holdout_period VARCHAR, metrics VARCHAR, gates VARCHAR, importance VARCHAR,
                 artifact VARCHAR, approved_by VARCHAR, promoted_at VARCHAR, retired_at VARCHAR, notes VARCHAR""",
    "DRIFT_REPORTS": """object VARCHAR, period VARCHAR, champion_version VARCHAR, status VARCHAR,
                 max_psi DOUBLE, top_feature VARCHAR, report VARCHAR, created_at VARCHAR""",
    "CYCLE_LOG": """object VARCHAR, period VARCHAR, record VARCHAR, created_at VARCHAR""",
    "AUDIT_LOG": """ts VARCHAR, agent VARCHAR, action VARCHAR, object VARCHAR, period VARCHAR,
                 version VARCHAR, detail VARCHAR""",
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Warehouse:
    """Interface. Subclasses implement query, execute and _write."""

    name = "base"

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def execute(self, sql: str, params: list | None = None) -> None:  # pragma: no cover
        raise NotImplementedError

    def _write(self, table: str, df: pd.DataFrame, replace: bool) -> None:  # pragma: no cover
        raise NotImplementedError

    def table_exists(self, table: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    # ---------------------------------------------------------------- helpers
    def ensure_schema(self) -> None:
        for table, cols in _DDL.items():
            self.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")

    def reset_lifecycle(self) -> None:
        """Empty registry, scores, reports and logs. Used before a replay."""
        for table in _DDL:
            self.execute(f"DELETE FROM {table}")

    def write(self, table: str, df: pd.DataFrame, replace: bool = False) -> None:
        if len(df):
            self._write(table, df.reset_index(drop=True), replace)

    def load_object_data(self, obj: str, periods: list[str] | None = None) -> pd.DataFrame:
        table = DATA_TABLES[obj]
        if periods:
            marks = ",".join(["?"] * len(periods))
            return self.query(f"SELECT * FROM {table} WHERE period IN ({marks})", list(periods))
        return self.query(f"SELECT * FROM {table}")

    def periods(self, obj: str) -> list[str]:
        df = self.query(f"SELECT DISTINCT period FROM {DATA_TABLES[obj]} ORDER BY period")
        return df["period"].tolist()

    def audit(self, agent: str, action: str, obj: str, period: str | None = None,
              version: str | None = None, detail: dict | None = None) -> None:
        self.write("AUDIT_LOG", pd.DataFrame([{
            "ts": now(), "agent": agent, "action": action, "object": obj, "period": period or "",
            "version": version or "", "detail": json.dumps(detail or {}, default=str),
        }]))


class DuckDBWarehouse(Warehouse):
    name = "duckdb"

    def __init__(self, path: str = "warehouse.duckdb"):
        import duckdb
        self.path = path
        self.con = duckdb.connect(path)
        self.ensure_schema()

    def query(self, sql, params=None):
        return self.con.execute(sql, params or []).fetchdf()

    def execute(self, sql, params=None):
        self.con.execute(sql, params or [])

    def table_exists(self, table):
        return bool(self.con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE upper(table_name) = ?", [table.upper()]
        ).fetchone()[0])

    def _write(self, table, df, replace):
        self.con.register("_incoming", df)
        if replace or not self.table_exists(table):
            self.con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _incoming")
        else:
            cols = ", ".join(f'"{c}"' for c in df.columns)
            self.con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _incoming")
        self.con.unregister("_incoming")

    def close(self):
        self.con.close()


class SnowflakeWarehouse(Warehouse):
    """Live mode. Reads SNOWFLAKE_* environment variables.

    Auth: set SNOWFLAKE_PRIVATE_KEY_FILE for key-pair auth (recommended), or
    SNOWFLAKE_PASSWORD with a programmatic access token. Password-only human
    logins are being phased out by Snowflake, so avoid them.
    """

    name = "snowflake"

    def __init__(self):
        import snowflake.connector
        snowflake.connector.paramstyle = "qmark"
        kwargs = dict(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            role=os.getenv("SNOWFLAKE_ROLE", "CRM_AGENT"),
            warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "CRM_WH"),
            database=os.getenv("SNOWFLAKE_DATABASE", "CRM_SCORING"),
            schema=os.getenv("SNOWFLAKE_SCHEMA", "LIFECYCLE"),
        )
        if os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE"):
            kwargs["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"]
        else:
            kwargs["password"] = os.environ["SNOWFLAKE_PASSWORD"]
        self.con = snowflake.connector.connect(**kwargs)
        self.ensure_schema()

    def query(self, sql, params=None):
        cur = self.con.cursor()
        try:
            cur.execute(sql, params or [])
            df = cur.fetch_pandas_all()
        finally:
            cur.close()
        df.columns = [c.lower() for c in df.columns]
        return df

    def execute(self, sql, params=None):
        cur = self.con.cursor()
        try:
            cur.execute(sql, params or [])
        finally:
            cur.close()

    def table_exists(self, table):
        cur = self.con.cursor()
        try:
            cur.execute(f"SHOW TABLES LIKE '{table.upper()}'")
            return len(cur.fetchall()) > 0
        finally:
            cur.close()

    def _write(self, table, df, replace):
        # Small appends (audit rows, registry rows) go through a plain INSERT. Bulk loads use write_pandas.
        if not replace and len(df) <= 200 and self.table_exists(table):
            cols = ", ".join(c.upper() for c in df.columns)
            marks = ", ".join(["?"] * len(df.columns))
            rows = [tuple(None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r)
                    for r in df.itertuples(index=False)]
            cur = self.con.cursor()
            try:
                cur.executemany(f"INSERT INTO {table} ({cols}) VALUES ({marks})", rows)
            finally:
                cur.close()
            return
        from snowflake.connector.pandas_tools import write_pandas
        out = df.copy()
        out.columns = [c.upper() for c in out.columns]
        write_pandas(self.con, out, table.upper(), auto_create_table=True,
                     overwrite=replace, quote_identifiers=False)


def get_warehouse(kind: str | None = None, path: str | None = None) -> Warehouse:
    kind = (kind or os.getenv("CRM_WAREHOUSE", "duckdb")).lower()
    if kind == "snowflake":
        return SnowflakeWarehouse()
    return DuckDBWarehouse(path or os.getenv("CRM_DUCKDB_PATH", "warehouse.duckdb"))
