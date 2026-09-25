"""MCP server: every lifecycle step as a tool.

Any MCP client can drive the lifecycle conversationally: Claude Desktop, Claude
Code, Cursor, or an Agentforce agent through Salesforce's MCP client support.

    python -m crmscore.mcp_server          # stdio transport

Example asks once connected:
    "Check drift on leads for 2026-03 and tell me what changed."
    "Why was account-v12 promoted over the fine-tune?"
    "Explain the score for lead L-202609-24011."
    "Roll back the lead model; marketing says the new one is off."
"""
from __future__ import annotations

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .agents.a2a import InProcessTransport, to_jsonable
from .agents.orchestrator import run_cycle
from .service import build_lifecycle

mcp = FastMCP("crm-scoring-agents")
_lc = None
_tx = None


def lc():
    global _lc, _tx
    if _lc is None:
        _lc = build_lifecycle()
        _tx = InProcessTransport(_lc)
    return _lc


def tx():
    lc()
    return _tx


@mcp.tool()
def lifecycle_status() -> dict:
    """Current champion for each object, plus the latest cycle's status and decision."""
    out = {}
    for obj in ("lead", "account"):
        cycles = lc().cycles(obj)
        last = cycles[-1] if cycles else {}
        out[obj] = {"champion": lc().champion_version(obj), "last_period": last.get("period"),
                    "last_status": last.get("monitor", {}).get("status"),
                    "last_decision": last.get("decision", {}).get("action"), "summary": last.get("summary")}
    return out


@mcp.tool()
def list_models(obj: str) -> list[dict]:
    """Model registry for 'lead' or 'account': version, status, method, windows, approver."""
    reg = lc().registry(obj)
    cols = ["version", "status", "method", "parent_version", "train_window", "holdout_period",
            "approved_by", "promoted_at", "notes"]
    return to_jsonable(reg[cols].to_dict("records"))


@mcp.tool()
def get_model_card(version: str) -> str:
    """Markdown model card: windows, holdout metrics, segment AUC, importance, gate results."""
    return lc().model_card(version)


@mcp.tool()
def check_drift(obj: str, period: str) -> dict:
    """Monitor Agent. Input drift (PSI), unseen categories and outcome performance for a period.
    Periods look like '2026-03' for leads and '2026Q1' for accounts."""
    return tx().send("monitor-agent", "check_drift", {"obj": obj, "period": period})


@mcp.tool()
def build_challengers(obj: str, period: str, methods: list[str] | None = None) -> dict:
    """Builder Agent. Train challengers. methods: any of recalibrate, finetune, retrain.
    Leave empty to let the builder plan from a fresh drift report."""
    payload = {"obj": obj, "period": period}
    if methods:
        payload["methods"] = methods
    else:
        payload["report"] = check_drift(obj, period)
    return tx().send("builder-agent", "build_challengers", payload)


@mcp.tool()
def run_lifecycle_cycle(obj: str, period: str, approve: bool = False, approver: str = "",
                        dry_run: bool = True) -> dict:
    """Full cycle: monitor, build, gate, promote or hold, score and write back.
    Account promotions need approve=True and an approver name. dry_run=True skips CRM writes."""
    rec = run_cycle(tx(), obj, period, approve=approve, approver=approver, dry_run=dry_run)
    return {k: rec[k] for k in ("object", "period", "monitor", "plan", "challengers", "decision", "scoring", "summary")}


@mcp.tool()
def approve_promotion(version: str, approver: str) -> dict:
    """Human approval for a challenger in pending_approval status."""
    return tx().send("governance-agent", "approve", {"version": version, "approver": approver})


@mcp.tool()
def rollback_model(obj: str, reason: str) -> dict:
    """Restore the previous champion for 'lead' or 'account'. Logged to the audit trail."""
    return tx().send("governance-agent", "rollback", {"obj": obj, "reason": reason})


@mcp.tool()
def explain_record(obj: str, record_id: str) -> dict:
    """Score, tier and the features that moved it, for one account or lead id."""
    return to_jsonable(lc().explain_record(obj, record_id))


@mcp.tool()
def audit_trail(obj: str, limit: int = 20) -> list[dict]:
    """Most recent agent actions for an object: who did what, when and why."""
    df = lc().wh.query("SELECT * FROM AUDIT_LOG WHERE object = ? ORDER BY ts DESC", [obj]).head(limit)
    return to_jsonable(df.to_dict("records"))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
