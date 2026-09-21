"""Тесты S4-04: trust-тиры — авто-политики, смена тира, маппинг в фабрике."""
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

from src.db import database  # noqa: E402
from src.runtime import TIER_LIMITS, tier_policy_template, tier_simulation_mode  # noqa: E402
from src.security.dharma import compile_yaml  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client, username="onb-user") -> str:
    client.post("/api/v1/auth/register",
                json={"username": username, "password": "pass12345"})
    response = client.post("/api/v1/auth/token",
                           json={"username": username, "password": "pass12345"})
    return response.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _create(client, token, **overrides):
    body = {"name": "onb-agent", "chain_id": 11155111}
    body.update(overrides)
    response = client.post("/api/v1/agents", json=body, headers=_h(token))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_agent_with_tier_and_auto_policy(client):
    token = _auth(client)
    agent = _create(client, token, tier=1)
    assert agent["tier"] == 1

    policy = client.get(f"/api/v1/agents/{agent['id']}/policy", headers=_h(token))
    assert policy.status_code == 200
    body = policy.json()
    assert body["version"] == 1
    assert body["compiled"]["model"]["limits"]["per_tx_eth"] == 0.5


def test_default_tier_is_demo(client):
    token = _auth(client)
    agent = _create(client, token)
    assert agent["tier"] == 0
    policy = client.get(f"/api/v1/agents/{agent['id']}/policy", headers=_h(token))
    assert policy.json()["compiled"]["model"]["limits"]["per_tx_eth"] == 0.1


def test_set_tier_releases_new_policy_version(client):
    token = _auth(client)
    agent = _create(client, token, tier=2)
    first = client.get(f"/api/v1/agents/{agent['id']}/policy", headers=_h(token)).json()
    assert first["version"] == 1

    response = client.post(f"/api/v1/agents/{agent['id']}/tier",
                           json={"tier": 3}, headers=_h(token))
    assert response.status_code == 200
    assert response.json()["tier"] == 3

    second = client.get(f"/api/v1/agents/{agent['id']}/policy", headers=_h(token)).json()
    assert second["version"] == 2
    assert second["compiled"]["model"]["limits"]["per_tx_eth"] == 1.0  # tier 3


def test_invalid_tier_rejected(client):
    token = _auth(client)
    for bad in (5, -1):
        response = client.post("/api/v1/agents", json={"name": "bad", "tier": bad},
                               headers=_h(token))
        assert response.status_code == 422


def test_tier_templates_compile_and_map():
    for tier in range(4):
        compiled = compile_yaml(tier_policy_template(tier))
        assert compiled.model.limits.per_tx_eth == TIER_LIMITS[tier][0]
    assert tier_simulation_mode(0) is True
    assert tier_simulation_mode(1) is True
    assert tier_simulation_mode(2) is False
    assert tier_simulation_mode(3) is False


def test_factory_maps_tier(client):
    token = _auth(client)
    demo = _create(client, token, name="factory-demo", tier=0)
    live = _create(client, token, name="factory-live", tier=2)

    from src.db import AgentRepository, session_scope
    from src.runtime import build_agent

    async def _build(agent_id):
        async with session_scope() as session:
            row = await AgentRepository(session).get(uuid.UUID(agent_id))
            return await build_agent(row, event_sink=None)

    database.reset_engine()
    demo_agent = _run(_build(demo["id"]))
    live_agent = _run(_build(live["id"]))
    database.reset_engine()

    assert demo_agent.config.simulation_mode is True
    assert live_agent.config.simulation_mode is False
