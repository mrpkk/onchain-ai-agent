"""Тесты S2-03: WebSocket live-события + event_sink ядра."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402
from src.db import database  # noqa: E402


@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    asyncio.run(database.drop_all())
    asyncio.run(database.create_all())
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client) -> str:
    client.post("/api/v1/auth/register",
                json={"username": "ws-user", "password": "pass12345"})
    response = client.post("/api/v1/auth/token",
                           json={"username": "ws-user", "password": "pass12345"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _create_agent(client, token: str) -> str:
    response = client.post("/api/v1/agents", json={"name": "ws-agent"},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 201
    return response.json()["id"]


def test_ws_rejects_invalid_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=bad-token") as websocket:
            websocket.receive_json()


def test_ws_hello_and_agent_status_event(client):
    token = _auth(client)
    with client.websocket_connect(f"/ws?token={token}") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        assert hello["username"] == "ws-user"

        agent_id = _create_agent(client, token)
        client.post(f"/api/v1/agents/{agent_id}/start",
                    headers={"Authorization": f"Bearer {token}"})

        event = websocket.receive_json()
        assert event["type"] == "agent.status"
        assert event["agent_id"] == agent_id
        assert event["status"] == "running"


def test_ws_broadcast_to_multiple_clients(client):
    token = _auth(client)
    with client.websocket_connect(f"/ws?token={token}") as first, \
            client.websocket_connect(f"/ws?token={token}") as second:
        assert first.receive_json()["type"] == "hello"
        assert second.receive_json()["type"] == "hello"

        agent_id = _create_agent(client, token)
        client.post(f"/api/v1/agents/{agent_id}/kill-switch",
                    json={"reason": "test drill"},
                    headers={"Authorization": f"Bearer {token}"})

        event_first = first.receive_json()
        event_second = second.receive_json()
        assert event_first == event_second
        assert event_first["type"] == "agent.status"
        assert event_first["status"] == "killed"
        assert event_first["reason"] == "test drill"


def test_core_event_sink_emits_decision():
    received: list[dict] = []

    async def sink(event: dict) -> None:
        received.append(event)

    agent = OnChainAgent(AgentConfig(name="sink-test", chain="sepolia"), event_sink=sink)
    decision = AgentDecision(action="hold", params={}, reasoning="test",
                             confidence=0.5, risk_level="low")
    asyncio.run(agent._persist_decision(decision))

    assert received, "sink не получил событие"
    assert received[0]["type"] == "decision.proposed"
    assert received[0]["action"] == "hold"


def test_core_sink_errors_do_not_break_agent():
    async def broken_sink(event: dict) -> None:
        raise RuntimeError("sink down")

    agent = OnChainAgent(AgentConfig(name="sink-broken", chain="sepolia"),
                         event_sink=broken_sink)
    decision = AgentDecision(action="hold", params={}, reasoning="r",
                             confidence=0.1, risk_level="low")
    asyncio.run(agent._persist_decision(decision))  # не должно бросить исключение
