"""Тесты S3-06: интеграция API⟷Runtime — start/stop/kill, heartbeat, pending, diary, audit."""
import asyncio
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.timelock import TimelockQueue  # noqa: E402
from src.db import database  # noqa: E402


class FakeRuntime:
    """Подмена OnChainAgent: без сети и без цикла восприятия."""

    def __init__(self):
        self.started = False
        self.stopped = False
        self.killed = None
        self.heartbeats = 0
        self.timelock = TimelockQueue()
        self._stop_event = None

    async def start(self):
        self.started = True
        self._stop_event = asyncio.Event()
        await self._stop_event.wait()

    async def stop(self):
        self.stopped = True
        if self._stop_event is not None:
            self._stop_event.set()

    def trigger_kill_switch(self, mode="hard", reason=""):
        self.killed = (mode, reason)

    def heartbeat(self):
        self.heartbeats += 1

    def cancel_pending(self, item_id: str) -> bool:
        return self.timelock.cancel(item_id)


@pytest.fixture
def env(monkeypatch):
    from src.api import main as main_module
    from src.runtime import manager as runtime_manager

    database.reset_engine()
    asyncio.run(database.drop_all())
    asyncio.run(database.create_all())
    runtime_manager.reset()

    created: dict[str, FakeRuntime] = {}

    async def fake_build(agent_row, *, event_sink=None, **kwargs):
        runtime = FakeRuntime()
        created[str(agent_row.id)] = runtime
        return runtime

    monkeypatch.setattr(main_module, "build_agent", fake_build)
    with TestClient(main_module.app) as client:
        yield client, created, runtime_manager
    runtime_manager.reset()


def _auth(client, username="rt-user") -> str:
    client.post("/api/v1/auth/register",
                json={"username": username, "password": "pass12345"})
    response = client.post("/api/v1/auth/token",
                           json={"username": username, "password": "pass12345"})
    return response.json()["access_token"]


def _agent(client, token) -> str:
    response = client.post("/api/v1/agents", json={"name": "rt-agent"},
                           headers={"Authorization": f"Bearer {token}"})
    return response.json()["id"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_start_creates_runtime(env):
    client, created, runtime_manager = env
    token = _auth(client)
    agent_id = _agent(client, token)

    response = client.post(f"/api/v1/agents/{agent_id}/start", headers=_h(token))
    assert response.status_code == 200
    assert runtime_manager.is_running(agent_id) is True
    assert created[agent_id].started is True


def test_stop_stops_runtime(env):
    client, created, runtime_manager = env
    token = _auth(client)
    agent_id = _agent(client, token)
    client.post(f"/api/v1/agents/{agent_id}/start", headers=_h(token))

    response = client.post(f"/api/v1/agents/{agent_id}/stop", headers=_h(token))
    assert response.status_code == 200
    assert created[agent_id].stopped is True
    assert runtime_manager.is_running(agent_id) is False


def test_kill_switch_kills_runtime(env):
    client, created, runtime_manager = env
    token = _auth(client)
    agent_id = _agent(client, token)
    client.post(f"/api/v1/agents/{agent_id}/start", headers=_h(token))

    response = client.post(f"/api/v1/agents/{agent_id}/kill-switch",
                           json={"reason": "drill"}, headers=_h(token))
    assert response.status_code == 200
    assert created[agent_id].killed == ("hard", "drill")
    assert runtime_manager.is_running(agent_id) is False


def test_heartbeat_endpoint(env):
    client, created, _ = env
    token = _auth(client)
    agent_id = _agent(client, token)

    not_running = client.post(f"/api/v1/agents/{agent_id}/heartbeat", headers=_h(token))
    assert not_running.status_code == 409

    client.post(f"/api/v1/agents/{agent_id}/start", headers=_h(token))
    ok = client.post(f"/api/v1/agents/{agent_id}/heartbeat", headers=_h(token))
    assert ok.status_code == 200
    assert created[agent_id].heartbeats == 1


def test_pending_list_and_cancel(env):
    client, created, _ = env
    token = _auth(client)
    agent_id = _agent(client, token)
    client.post(f"/api/v1/agents/{agent_id}/start", headers=_h(token))

    item = created[agent_id].timelock.schedule("transfer", {"to": "0xabc", "amount": 0.5}, 300)
    listing = client.get(f"/api/v1/agents/{agent_id}/pending", headers=_h(token))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["pending"][0]["id"] == item.id

    cancelled = client.post(f"/api/v1/agents/{agent_id}/pending/{item.id}/cancel",
                            headers=_h(token))
    assert cancelled.status_code == 200 and cancelled.json()["cancelled"] == item.id

    again = client.post(f"/api/v1/agents/{agent_id}/pending/{item.id}/cancel",
                        headers=_h(token))
    assert again.status_code == 404


def test_decisions_endpoint(env):
    client, _created, _ = env
    token = _auth(client)
    agent_id = _agent(client, token)

    async def _seed():
        from src.db import DecisionRepository, session_scope
        async with session_scope() as session:
            await DecisionRepository(session).add(
                uuid.UUID(agent_id), action="transfer", reasoning="diary",
                confidence=0.8, risk_level="low",
            )

    database.reset_engine()
    asyncio.run(_seed())
    database.reset_engine()

    response = client.get(f"/api/v1/agents/{agent_id}/decisions", headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["decisions"][0]["action"] == "transfer"
    assert body["decisions"][0]["confidence"] == pytest.approx(0.8)


def test_audit_endpoint(env, monkeypatch):
    client, _created, _ = env
    monkeypatch.setenv("SAKSHI_AUDIT_KEY", "test-audit-key")
    token = _auth(client)
    agent_id = _agent(client, token)

    async def _seed():
        from src.db import session_scope
        from src.security.sakshi import SakshiLog
        async with session_scope() as session:
            await SakshiLog("test-audit-key").append(
                session, actor="agent", event_type="decision_made",
                payload={"action": "hold"}, agent_id=uuid.UUID(agent_id),
            )

    database.reset_engine()
    asyncio.run(_seed())
    database.reset_engine()

    response = client.get(f"/api/v1/agents/{agent_id}/audit", headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["event_type"] == "decision_made"
    assert body["events"][0]["hash"]


def test_factory_builds_agent_with_policy(env):
    client, _created, _ = env
    token = _auth(client)
    agent_id = _agent(client, token)
    client.put(f"/api/v1/agents/{agent_id}/policy",
               json={"dsl_yaml": "limits: {per_tx_eth: 0.33, daily_eth: 1.0}\n"},
               headers=_h(token))

    from src.db import AgentRepository, session_scope
    from src.runtime import build_agent

    async def _build():
        async with session_scope() as session:
            row = await AgentRepository(session).get(uuid.UUID(agent_id))
            return await build_agent(row, event_sink=None)

    database.reset_engine()
    agent = asyncio.run(_build())
    database.reset_engine()

    assert agent.policy.model.limits.per_tx_eth == pytest.approx(0.33)
    assert str(agent._db_agent_id) == agent_id


def test_factory_default_policy_without_dsl(env):
    client, _created, _ = env
    token = _auth(client)
    agent_id = _agent(client, token)

    from src.db import AgentRepository, session_scope
    from src.runtime import build_agent

    async def _build():
        async with session_scope() as session:
            row = await AgentRepository(session).get(uuid.UUID(agent_id))
            return await build_agent(row, event_sink=None)

    database.reset_engine()
    agent = asyncio.run(_build())
    database.reset_engine()

    assert agent.policy.model.limits.per_tx_eth == pytest.approx(1.0)  # дефолт
