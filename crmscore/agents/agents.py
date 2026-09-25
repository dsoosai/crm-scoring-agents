"""The three lifecycle agents.

Separation of duties, the same way a bank separates who builds a model from
who approves it:

* Monitor Agent     watches inputs and outcomes, and says what is wrong.
* Builder Agent     decides which update paths to try and builds challengers.
                    It cannot promote anything.
* Governance Agent  runs the promotion gates, promotes or holds, asks for human
                    approval where policy requires it, scores and writes back
                    to the CRM, and can roll back.

Each agent publishes an A2A agent card and handles one JSON message per skill.
The same handlers run in-process for the demo, or behind HTTP for A2A.
"""
from __future__ import annotations

from ..lifecycle import Lifecycle


class Agent:
    name = "agent"
    description = ""
    skills: list[dict] = []

    def __init__(self, lc: Lifecycle):
        self.lc = lc

    def handle(self, skill: str, payload: dict) -> dict:
        fn = getattr(self, f"skill_{skill}", None)
        if fn is None:
            raise ValueError(f"{self.name} has no skill '{skill}'")
        return fn(**payload)

    def card(self, url: str) -> dict:
        """A2A agent card (protocol 0.3 field names)."""
        return {
            "protocolVersion": "0.3.0",
            "name": self.name,
            "description": self.description,
            "url": url,
            "preferredTransport": "JSONRPC",
            "version": "1.0.0",
            "provider": {"organization": "crm-scoring-agents", "url": "https://github.com/dsoosai/crm-scoring-agents"},
            "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [{**s, "inputModes": ["application/json"], "outputModes": ["application/json"]} for s in self.skills],
        }


class MonitorAgent(Agent):
    name = "monitor-agent"
    description = ("Watches a CRM scoring model in production. Measures input drift (PSI), unseen categories, "
                   "and outcome performance once labels arrive. Returns findings and recommended update paths.")
    skills = [{"id": "check_drift", "name": "Check drift",
               "description": "Drift and performance report for one object and period.",
               "tags": ["drift", "monitoring", "psi"],
               "examples": ['{"skill": "check_drift", "input": {"obj": "lead", "period": "2026-03"}}']}]

    def skill_check_drift(self, obj: str, period: str) -> dict:
        return self.lc.monitor(obj, period, actor=self.name)


class BuilderAgent(Agent):
    name = "builder-agent"
    description = ("Builds challenger models. Chooses between recalibration, warm-start fine-tuning and a full "
                   "retrain based on the monitor's findings and the object's rebuild cadence.")
    skills = [{"id": "build_challengers", "name": "Build challengers",
               "description": "Plan update paths from a drift report, then train and register challengers.",
               "tags": ["training", "fine-tuning", "calibration"],
               "examples": ['{"skill": "build_challengers", "input": {"obj": "lead", "period": "2026-03", "report": {}}}']}]

    def plan(self, obj: str, period: str, report: dict) -> tuple[list[str], list[str]]:
        methods, why = set(report.get("recommended_methods", [])), []
        cadence = self.lc.ocfg(obj)["cadence"]
        methods.add("retrain")
        why.append(f"Scheduled {cadence} rebuild: always build a full-retrain challenger.")
        unseen = report.get("unseen_categories") or {}
        if unseen:
            win = self.lc.windows(obj, period)
            labeled = self.lc.data(obj, win["train"], labeled=True)
            for feat, u in unseen.items():
                have = [v for v in u["values"] if v in set(labeled[feat].astype(str))]
                wait = [v for v in u["values"] if v not in have]
                if have:
                    why.append(f"New {feat} values {', '.join(have)} now have outcomes in the training window. "
                               "Only a full retrain can learn them.")
                if wait:
                    why.append(f"New {feat} values {', '.join(wait)} have no outcomes yet. The champion treats them "
                               "as unknown until labels land; no update path can learn them this cycle.")
        if "recalibrate" in methods:
            why.append("Calibration gap found: try the cheapest fix, a recalibration.")
        if "finetune" in methods:
            why.append("Performance or input drift: try a warm-start fine-tune on the latest labeled data.")
        order = self.lc.cfg["methods_cost_order"]
        return sorted(methods, key=order.index), why

    def skill_build_challengers(self, obj: str, period: str, report: dict | None = None,
                                methods: list[str] | None = None) -> dict:
        if methods:
            why = ["Methods set by caller."]
        else:
            methods, why = self.plan(obj, period, report or {})
        result = self.lc.build_challengers(obj, period, methods, actor=self.name)
        result["plan"] = {"methods": methods, "why": why}
        return result


class GovernanceAgent(Agent):
    name = "governance-agent"
    description = ("Owns promotion. Runs gates against the champion on an out-of-time holdout, promotes or holds, "
                   "requests human approval where policy says so, scores and writes back to the CRM, rolls back.")
    skills = [
        {"id": "evaluate_and_promote", "name": "Evaluate and promote",
         "description": "Gate every challenger and promote the cheapest one that passes, or hold.",
         "tags": ["governance", "promotion", "gates"], "examples": []},
        {"id": "score_and_write_back", "name": "Score and write back",
         "description": "Score the period with the champion and update Salesforce fields.",
         "tags": ["scoring", "salesforce"], "examples": []},
        {"id": "approve", "name": "Approve", "description": "Human approval of a pending challenger.",
         "tags": ["approval"], "examples": []},
        {"id": "rollback", "name": "Rollback", "description": "Restore the previous champion.",
         "tags": ["rollback"], "examples": []},
        {"id": "record_cycle", "name": "Record cycle", "description": "Persist the cycle record.",
         "tags": ["audit"], "examples": []},
    ]

    def skill_evaluate_and_promote(self, obj: str, period: str, build: dict, approve: bool = False,
                                   approver: str = "") -> dict:
        gates = self.lc.gate_check(obj, period, build)
        decision = self.lc.decide(obj, period, gates, approve=approve, approver=approver, actor=self.name)
        return {"gates": gates, "decision": decision}

    def skill_score_and_write_back(self, obj: str, period: str, dry_run: bool = False) -> dict:
        return self.lc.score(obj, period, dry_run=dry_run, actor=self.name)

    def skill_approve(self, version: str, approver: str) -> dict:
        return self.lc.approve(version, approver)

    def skill_rollback(self, obj: str, reason: str = "") -> dict:
        return self.lc.rollback(obj, reason, actor=self.name)

    def skill_record_cycle(self, obj: str, period: str, record: dict) -> dict:
        self.lc.log_cycle(obj, period, record)
        return {"recorded": True}


def build_agents(lc: Lifecycle) -> dict[str, Agent]:
    return {a.name: a for a in (MonitorAgent(lc), BuilderAgent(lc), GovernanceAgent(lc))}
