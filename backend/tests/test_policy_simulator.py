"""Тесты S4-11/S4-12: Policy Simulator и Trust Ladder."""
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

from src.db import (  # noqa: E402
    AgentRepository,
    DecisionRepository,
    PolicyRepository,
    UserRepository,
    database,
    session_scope,
)
from src.runtime.policy_simulator import simulate_policy_change  # noqa: E402
from src.runtime.tiers import trust_ladder_rung  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Trust Ladder: unit ────────────────────────────────────────────────

def test_trust_ladder_mapping():
    assert trust_ladder_rung(0)["rung"] == "simulate"
    assert trust_ladder_rung(1)["rung"] == "simulate"
    assert trust_ladder_rung(2, simulation_mode=False, undo_window_seconds=300)["rung"] == "approve"
    assert trust_ladder_rung(2, simulation_mode=False, undo_window_seconds=0,
                             approvals_amount_eth=0.0)["rung"] == "limited_auto"
    assert trust_ladder_rung(3, simulation_mode=False, undo_window_seconds=0)["rung"] == "autonomous"
    assert trust_ladder_rung(3, simulation_mode=False, undo_window_seconds=120)["rung"] == "limited_auto"


# ── Policy Simulator: unit (БД) ───────────────────────────────────────

@pytest.fixture
def db_env():
    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    yield


def _seed_decisions():
    async def _seed():
        async with session_scope() as session:
            user = await UserRepository(session).create("sim-user", "h")
            agent = await AgentRepository(session).create(user.id, name="sim-agent")
            repo = DecisionRepository(session)
            await repo.add(agent.id, action="transfer",
                           params={"to": "0x" + "ab" * 20, "amount": 0.5})
            await repo.add(agent.id, action="transfer",
                           params={"to": "0x" + "ab" * 20, "amount": 0.05})
            return agent.id

    return _run(_seed())


def test_policy_simulator_tightens(db_env):
    agent_id = _seed_decisions()

    async def _sim():
        async with session_scope() as session:
            return await simulate_policy_change(
                session, agent_id,
                "limits: {per_tx_eth: 0.1, daily_eth: 5.0}\n",
                chain_id=11155111,
            )

    result = _run(_sim())
    assert result["decisions_analyzed"] == 2
    assert result["summary"]["tightened"] == 1  # 0.5 > 0.1 → deny
    assert result["summary"]["unchanged"] == 1  # 0.05 остаётся allow
    assert result["applied"] is False
    assert result["changes"][0]["after"] == "deny"
    assert "НЕ применена" in result["note"]


def test_policy_simulator_relaxes(db_env):
    agent_id = _seed_decisions()

    async def _sim():
        async with session_scope() as session:
            await PolicyRepository(session).create_version(
                agent_id, "limits: {per_tx_eth: 0.01, daily_eth: 5.0}\n", {},
            )
            return await simulate_policy_change(
                session, agent_id, "limits: {per_tx_eth: 1.0, daily_eth: 5.0}\n",
                chain_id=11155111,
            )

    result = _run(_sim())
    assert result["summary"]["relaxed"] == 2  # оба переходят deny → allow


# ── API ───────────────────────────────────────────────────────────────

@pytest.fixture
def client_env():
    from src.api import main as main_module

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    with TestClient(main_module.app) as client:
        yield client


def _auth(client) -> str:
    client.post("/api/v1/auth/register",
                json={"username": "sim-api-user", "password": "pass12345"})
    return client.post("/api/v1/auth/token",
                       json={"username": "sim-api-user", "password": "pass12345"}).json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_policy_simulate_endpoint(client_env):
    client = client_env
    token = _auth(client)
    agent_id = client.post("/api/v1/agents", json={"name": "sim-api-agent"},
                           headers=_h(token)).json()["id"]

    async def _seed_decision():
        async with session_scope() as session:
            await DecisionRepository(session).add(
                uuid.UUID(agent_id), action="transfer",
                params={"to": "0x" + "ab" * 20, "amount": 0.08},
            )

    database.reset_engine()
    _run(_seed_decision())
    database.reset_engine()

    response = client.post(f"/api/v1/agents/{agent_id}/policy/simulate",
                           json={"dsl_yaml": "limits: {per_tx_eth: 0.05, daily_eth: 5.0}\n"},
                           headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["decisions_analyzed"] == 1
    assert body["summary"]["tightened"] == 1
    assert body["applied"] is False

    invalid = client.post(f"/api/v1/agents/{agent_id}/policy/simulate",
                          json={"dsl_yaml": "limits: {per_tx_eth: -1}\n"}, headers=_h(token))
    assert invalid.status_code == 422


def test_summary_includes_trust_ladder(client_env):
    client = client_env
    token = _auth(client)
    agent_id = client.post("/api/v1/agents", json={"name": "ladder-agent", "tier": 2},
                           headers=_h(token)).json()["id"]
    response = client.get(f"/api/v1/agents/{agent_id}/reports/summary", headers=_h(token))
    trust = response.json()["trust"]
    assert trust["rung"] == "approve"  # tier 2 c авто-политикой (undo 300)
    assert trust["rung_index"] == 3
    assert len(trust["ladder"]) == 6
