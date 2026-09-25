"""Lifecycle orchestrator. One cycle = four agent messages.

    monitor-agent.check_drift
      -> builder-agent.build_challengers        (plans methods from the report)
      -> governance-agent.evaluate_and_promote  (gates, promote or hold, approval)
      -> governance-agent.score_and_write_back  (champion scores the period, CRM updated)
      -> governance-agent.record_cycle

Works over any transport with a .send(agent, skill, payload) method.
"""
from __future__ import annotations

from ..narrate import summarize


def run_cycle(transport, obj: str, period: str, approve: bool = False, approver: str = "",
              dry_run: bool = False) -> dict:
    report = transport.send("monitor-agent", "check_drift", {"obj": obj, "period": period})
    build = transport.send("builder-agent", "build_challengers", {"obj": obj, "period": period, "report": report})
    gov = transport.send("governance-agent", "evaluate_and_promote",
                         {"obj": obj, "period": period, "build": build, "approve": approve, "approver": approver})
    scoring = transport.send("governance-agent", "score_and_write_back",
                             {"obj": obj, "period": period, "dry_run": dry_run})

    decision = gov["decision"]
    record = {
        "object": obj, "period": period, "transport": transport.name,
        "champion_before": report["champion"],
        "champion_after": scoring["model_version"],
        "monitor": {k: report[k] for k in ("status", "findings", "score_psi", "auc_drop", "labels_through",
                                            "recommended_methods", "frozen_v1_auc", "rules_v0_auc",
                                            "unseen_categories")},
        "feature_drift": [{k: d.get(k) for k in ("feature", "kind", "psi", "unseen_share")} for d in report["feature_drift"]],
        "champion_perf": report["performance"],
        "plan": build["plan"],
        "methods": [c["method"] for c in build["challengers"]],
        "challengers": [{"version": c["version"], "method": c["method"], "auc": c["metrics"]["auc"],
                         "passed": c["passed"], "tier_churn": c["tier_churn"],
                         "unknown_category_share": c["unknown_category_share"],
                         "failed_gates": [g["gate"] for g in c["gates"] if not g["passed"]]}
                        for c in gov["gates"]["candidates"]],
        "champion_holdout_auc": gov["gates"]["champion_metrics"]["auc"],
        "decision": decision,
        "scoring": scoring,
        "messages": list(getattr(transport, "log", []))[-4:],
    }
    record["summary"], record["summary_source"] = summarize(record)
    transport.send("governance-agent", "record_cycle", {"obj": obj, "period": period, "record": record})
    return record
