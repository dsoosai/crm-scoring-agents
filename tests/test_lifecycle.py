from crmscore.agents.a2a import InProcessTransport
from crmscore.agents.orchestrator import run_cycle


def test_bootstrap_creates_one_champion(lc):
    assert lc.champion_version("lead") == "lead-v1"
    assert lc.champion_version("account") == "account-v1"


def test_cycle_runs_end_to_end(lc):
    tx = InProcessTransport(lc)
    rec = run_cycle(tx, "lead", "2025-07")
    assert rec["monitor"]["status"] in {"healthy", "watch", "action"}
    assert "retrain" in rec["methods"]           # monthly rebuild is always tried
    assert rec["decision"]["action"] in {"promote", "hold"}
    assert rec["scoring"]["scored"] > 0
    assert [m["skill"] for m in rec["messages"]] == [
        "check_drift", "build_challengers", "evaluate_and_promote", "score_and_write_back"]


def test_unseen_category_is_found(lc):
    rep = lc.monitor("lead", "2026-03")
    assert "keyword" in rep["unseen_categories"]
    assert "AI Agents" in rep["unseen_categories"]["keyword"]["values"]
    assert "retrain" in rep["recommended_methods"]


def test_account_promotion_waits_for_approval(lc):
    tx = InProcessTransport(lc)
    build = tx.send("builder-agent", "build_challengers", {"obj": "account", "period": "2025Q4",
                                                           "methods": ["recalibrate", "retrain"]})
    out = tx.send("governance-agent", "evaluate_and_promote",
                  {"obj": "account", "period": "2025Q4", "build": build, "approve": False})
    if out["gates"]["chosen"]:
        assert out["decision"]["action"] == "pending_approval"
        assert lc.champion_version("account") == "account-v1"
        res = lc.approve(out["decision"]["candidate"], "Test approver")
        assert res["promoted"] is True
        assert lc.champion_version("account") == out["decision"]["candidate"]
        back = lc.rollback("account", "test")
        assert back["rolled_back"] and lc.champion_version("account") == "account-v1"


def test_gates_reject_a_worse_model(lc):
    build = lc.build_challengers("lead", "2025-08", ["recalibrate"])
    res = lc.gate_check("lead", "2025-08", build)
    beats = next(g for g in res["candidates"][0]["gates"] if g["gate"] == "beats_champion")
    assert beats["passed"] is False or res["champion_failing"]


def test_model_card_and_explain(lc):
    card = lc.model_card("lead-v1")
    assert "Holdout metrics" in card
    rec_id = lc.data("lead", ["2025-07"])["lead_id"].iat[0]
    ex = lc.explain_record("lead", rec_id)
    assert 0 <= ex["score"] <= 100 and ex["tier"] in "ABCD"
