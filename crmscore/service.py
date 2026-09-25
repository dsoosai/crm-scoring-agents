"""Wiring: build a Lifecycle from environment settings, and load demo data."""
from __future__ import annotations

import os

from .crm import get_crm
from .data.synth import generate_accounts, generate_leads
from .features import ACCOUNT, LEAD
from .lifecycle import Lifecycle, load_config
from .warehouse import get_warehouse


def build_lifecycle(warehouse: str | None = None, crm: str | None = None, workdir: str | None = None) -> Lifecycle:
    workdir = workdir or os.getenv("CRM_WORKDIR", ".")
    os.makedirs(workdir, exist_ok=True)
    wh = get_warehouse(warehouse, path=os.path.join(workdir, "warehouse.duckdb"))
    target = get_crm(crm, path=os.path.join(workdir, "mock_org.duckdb"))
    return Lifecycle(wh, target, load_config(os.getenv("CRM_CONFIG")))


def load_demo_data(lc: Lifecycle, seed_crm: bool = True) -> dict:
    """Generate synthetic CRM history, load it into the warehouse and seed the mock org."""
    accounts = generate_accounts()
    leads = generate_leads()
    lc.wh.write("ACCOUNT_SNAPSHOTS", accounts, replace=True)
    lc.wh.write("LEADS", leads, replace=True)
    lc.refresh_data()
    seeded = {}
    if seed_crm and lc.crm.name == "mock":
        latest = accounts[accounts["period"] == accounts["period"].max()]
        seeded["account"] = lc.crm.seed("account", latest, ACCOUNT.id_col, ACCOUNT.name_col)
        seeded["lead"] = lc.crm.seed("lead", leads, LEAD.id_col, LEAD.name_col)
    return {"account_rows": len(accounts), "lead_rows": len(leads), "seeded": seeded}
