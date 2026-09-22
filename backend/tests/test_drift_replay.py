"""Тесты S4-13/S4-14: Autonomy Drift Detection и Decision Replay v1."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import (  # noqa: E402
    AgentRepository,
    DecisionRepository,
    PolicyRepository,
    UserRepository,
    database,
    session_scope,
)
from src.runtime.drift import detect_drift  # noqa: E402
from src.runtime.replay import replay_decision  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_env():
    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    yield


# ── Drift Detection ───────────────────────────────────────────────────

def _seed_drift_decisions(agent_id, *, drift: bool):
    async def _seed():
        base = datetime.now(timezone.utc)
        async with session_scope() as session:
            repo = DecisionRepository(session)
            # previous window (6 решений, старые)
            for i in range(6):
                row = await repo.add(agent_id, action="hold", params={"amount": 0.01},
                                     reasoning="prev", risk_level="low")
                row.created_at = base - timedelta(hours=12 - i)
            # recent window (6 решений, новые)
            for i in range(6):
                action = "swap" if (drift and i == 0) else "hold"
                risk = "high" if (drift and i < 3) else "low"
                amount = 0.1 if drift else 0.01
                row = await repo.add(agent_id, action=action, params={"amount": amount},
                                     reasoning="recent", risk_level=risk)
                row.created_at = base - timedelta(minutes=30 - i)

    _run(_seed())


def _seed_agent(name="drift-agent"):
    async def _seed():
        async with session_scope() as session:
            user = await UserRepository(session).create(f"u-{name}", "h")
            agent = await AgentRepository(session).create(user.id, name=name)
            return agent.id

    return _run(_seed())


def test_drift_detects_signals(db_env):
    agent_id = _seed_agent("drift-yes")
    _seed_drift_decisions(agent_id, drift=True)

    async def _check():
        async with session_scope() as session:
            return await detect_drift(session, agent_id)

    result = _run(_check())
    types = {s["type"] for s in result["signals"]}
    assert "amount_spike" in types
    assert "new_actions" in types
    assert "risk_growth" in types
    assert result["level"] == "drift"
    assert result["drift_score"] == 75


def test_drift_stable(db_env):
    agent_id = _seed_agent("drift-no")
    _seed_drift_decisions(agent_id, drift=False)

    async def _check():
        async with session_scope() as session:
            return await detect_drift(session, agent_id)

    result = _run(_check())
    assert result["signals"] == []
    assert result["level"] == "stable"
    assert result["drift_score"] == 0


# ── Decision Replay ───────────────────────────────────────────────────

def _seed_replay(*, then_verdict, amount=0.6, policy_per_tx=0.5):
    async def _seed():
        async with session_scope() as session:
            user = await UserRepository(session).create("replay-user", "h")
            agent = await AgentRepository(session).create(user.id, name="replay-agent")
            await PolicyRepository(session).create_version(
                agent.id, f"limits: {{per_tx_eth: {policy_per_tx}, daily_eth: 5.0}}\n", {},
            )
            decision = await DecisionRepository(session).add(
                agent.id, action="transfer",
                params={"to": "0x" + "ab" * 20, "amount": amount},
                reasoning="r", policy_verdict=then_verdict,
            )
            return decision.id

    return _run(_seed())


def test_replay_shows_verdict_change(db_env):
    decision_id = _seed_replay(then_verdict={"decision": "allow"})

    async def _check():
        async with session_scope() as session:
            return await replay_decision(session, decision_id)

    result = _run(_check())
    assert result["then"]["decision"] == "allow"
    assert result["now"]["decision"] == "deny"  # 0.6 > 0.5 текущей политики
    assert result["verdict_changed"] is True
    assert "Phase 5" in result["note"]


def test_replay_without_stored_verdict(db_env):
    decision_id = _seed_replay(then_verdict=None)

    async def _check():
        async with session_scope() as session:
            return await replay_decision(session, decision_id)

    result = _run(_check())
    assert result["then"] is None
    assert result["verdict_changed"] is False


# ── API ───────────────────────────────────────────────────────────────

@pytest.fixture
def client_env():
    from src.api import main as main_module

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    with TestClient(main_module.app) as client:
        yield client


def _auth(client, username="dr-user") -> str:
    client.post("/api/v1/auth/register",
                json={"username": username, "password": "pass12345"})
    return client.post("/api/v1/auth/token",
                       json={"username": username, "password": "pass12345"}).json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_drift_and_replay_endpoints(client_env):
    client = client_env
    token = _auth(client)
    agent_id = client.post("/api/v1/agents", json={"name": "dr-agent"},
                           headers=_h(token)).json()["id"]

    async def _seed():
        async with session_scope() as session:
            return str((await DecisionRepository(session).add(
                uuid.UUID(agent_id), action="transfer",
                params={"to": "0x" + "ab" * 20, "amount": 0.08},
                policy_verdict={"decision": "allow"},
            )).id)

    database.reset_engine()
    decision_id = _run(_seed())
    database.reset_engine()

    drift = client.get(f"/api/v1/agents/{agent_id}/drift", headers=_h(token))
    assert drift.status_code == 200
    assert drift.json()["level"] in ("stable", "watch", "drift")

    replay = client.get(f"/api/v1/decisions/{decision_id}", headers=_h(token))
    assert replay.status_code == 200
    body = replay.json()
    assert body["decision"]["action"] == "transfer"
    assert body["then"]["decision"] == "allow"
    assert body["now"]["decision"] == "allow"  # 0.08 < tier-0 per_tx 0.1

    other = _auth(client, "dr-other")
    assert client.get(f"/api/v1/decisions/{decision_id}", headers=_h(other)).status_code == 404
    assert client.get(f"/api/v1/decisions/{uuid.uuid4()}", headers=_h(token)).status_code == 404
