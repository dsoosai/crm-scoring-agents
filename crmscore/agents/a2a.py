"""A small, spec-shaped A2A layer: agent cards plus JSON-RPC `message/send`.

It implements the subset of the Agent2Agent protocol the lifecycle needs:

* GET  /agents/{name}/.well-known/agent-card.json   agent card (A2A 0.3 fields)
* POST /agents/{name}                                JSON-RPC 2.0, method "message/send"

A request carries one DataPart: {"skill": "<skill id>", "input": {...}}.
The reply is a completed Task whose single artifact holds a DataPart with the
result. No streaming and no push notifications; the lifecycle does not need
them. Swap in the official a2a-sdk later without changing the agents.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import numpy as np

try:  # module level, so FastAPI can resolve the Request annotation
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover - only the A2A server needs FastAPI
    FastAPI = Request = JSONResponse = None


def to_jsonable(obj):
    """Recursively convert numpy and pandas scalars, and NaN or inf to None, so any JSON encoder accepts it."""
    return _clean(json.loads(json.dumps(obj, default=_default)))


def _clean(o):
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    return o


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_message(skill: str, payload: dict) -> dict:
    return {"role": "user", "kind": "message", "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "data", "data": {"skill": skill, "input": to_jsonable(payload)}}]}


def make_task(message: dict, skill: str, result: dict | None, error: str | None = None) -> dict:
    task = {"kind": "task", "id": str(uuid.uuid4()), "contextId": str(uuid.uuid4()),
            "status": {"state": "failed" if error else "completed", "timestamp": _ts()},
            "history": [message], "artifacts": []}
    if error:
        task["status"]["message"] = {"role": "agent", "kind": "message", "messageId": str(uuid.uuid4()),
                                     "parts": [{"kind": "text", "text": error}]}
    else:
        task["artifacts"].append({"artifactId": str(uuid.uuid4()), "name": f"{skill} result",
                                  "parts": [{"kind": "data", "data": to_jsonable(result)}]})
    return task


# ------------------------------------------------------------------------ server

def create_app(lc=None, base_url: str = "http://127.0.0.1:9100"):
    """FastAPI app hosting all three agents. Each has its own card and endpoint."""
    from ..service import build_lifecycle
    from .agents import build_agents

    lc = lc or build_lifecycle()
    agents = build_agents(lc)
    app = FastAPI(title="CRM scoring lifecycle agents (A2A)")

    @app.get("/agents")
    def directory():
        return {"agents": [{"name": n, "card": f"{base_url}/agents/{n}/.well-known/agent-card.json"} for n in agents]}

    @app.get("/agents/{name}/.well-known/agent-card.json")
    def card(name: str):
        if name not in agents:
            return JSONResponse({"error": f"unknown agent {name}"}, status_code=404)
        return agents[name].card(f"{base_url}/agents/{name}")

    @app.post("/agents/{name}")
    async def rpc(name: str, request: Request):
        body = await request.json()
        rid = body.get("id")
        if name not in agents:
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": f"unknown agent {name}"}})
        if body.get("method") != "message/send":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})
        message = body.get("params", {}).get("message", {})
        data = next((p.get("data") for p in message.get("parts", []) if p.get("kind") == "data"), None)
        if not data or "skill" not in data:
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "expected a data part with 'skill'"}})
        try:
            result = agents[name].handle(data["skill"], data.get("input", {}))
            task = make_task(message, data["skill"], result)
        except Exception as exc:  # the task fails; the server stays up
            task = make_task(message, data["skill"], None, error=f"{type(exc).__name__}: {exc}")
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": task})

    return app


# ------------------------------------------------------------------------ transports

class InProcessTransport:
    """Calls the agents directly. Same messages, no network. The default for demos and tests."""

    name = "in-process"

    def __init__(self, lc):
        from .agents import build_agents
        self.agents = build_agents(lc)
        self.log: list[dict] = []

    def send(self, agent: str, skill: str, payload: dict) -> dict:
        message = make_message(skill, payload)
        result = self.agents[agent].handle(skill, message["parts"][0]["data"]["input"])
        task = make_task(message, skill, result)
        self.log.append({"to": agent, "skill": skill, "task_id": task["id"], "state": task["status"]["state"]})
        return task["artifacts"][0]["parts"][0]["data"]


class A2ATransport:
    """Talks to agents over HTTP using A2A JSON-RPC."""

    name = "a2a"

    def __init__(self, base_url: str = "http://127.0.0.1:9100", timeout: float = 600.0):
        import httpx
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(timeout=timeout)
        self.cards: dict[str, dict] = {}
        self.log: list[dict] = []

    def card(self, agent: str) -> dict:
        if agent not in self.cards:
            r = self.http.get(f"{self.base}/agents/{agent}/.well-known/agent-card.json")
            r.raise_for_status()
            self.cards[agent] = r.json()
        return self.cards[agent]

    def send(self, agent: str, skill: str, payload: dict) -> dict:
        card = self.card(agent)
        if skill not in {s["id"] for s in card["skills"]}:
            raise ValueError(f"{agent} does not advertise skill {skill}")
        body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "message/send",
                "params": {"message": make_message(skill, payload)}}
        r = self.http.post(card["url"], json=body)
        r.raise_for_status()
        reply = r.json()
        if "error" in reply:
            raise RuntimeError(f"{agent}.{skill}: {reply['error']['message']}")
        task = reply["result"]
        self.log.append({"to": agent, "skill": skill, "task_id": task["id"], "state": task["status"]["state"]})
        if task["status"]["state"] != "completed":
            raise RuntimeError(f"{agent}.{skill} failed: {task['status']['message']['parts'][0]['text']}")
        return task["artifacts"][0]["parts"][0]["data"]
