from fastapi.testclient import TestClient

from crmscore.agents.a2a import create_app, make_message


def test_agent_cards_and_message_send(lc):
    client = TestClient(create_app(lc, base_url="http://testserver"))
    names = [a["name"] for a in client.get("/agents").json()["agents"]]
    assert names == ["monitor-agent", "builder-agent", "governance-agent"]
    card = client.get("/agents/monitor-agent/.well-known/agent-card.json").json()
    assert card["protocolVersion"] and card["skills"][0]["id"] == "check_drift"

    body = {"jsonrpc": "2.0", "id": "1", "method": "message/send",
            "params": {"message": make_message("check_drift", {"obj": "lead", "period": "2025-08"})}}
    task = client.post("/agents/monitor-agent", json=body).json()["result"]
    assert task["kind"] == "task" and task["status"]["state"] == "completed"
    assert task["artifacts"][0]["parts"][0]["data"]["period"] == "2025-08"


def test_unknown_skill_fails_the_task_not_the_server(lc):
    client = TestClient(create_app(lc, base_url="http://testserver"))
    body = {"jsonrpc": "2.0", "id": "2", "method": "message/send",
            "params": {"message": make_message("does_not_exist", {})}}
    task = client.post("/agents/monitor-agent", json=body).json()["result"]
    assert task["status"]["state"] == "failed"


def test_wrong_method_is_a_jsonrpc_error(lc):
    client = TestClient(create_app(lc, base_url="http://testserver"))
    r = client.post("/agents/monitor-agent", json={"jsonrpc": "2.0", "id": "3", "method": "tasks/get", "params": {}})
    assert r.json()["error"]["code"] == -32601
