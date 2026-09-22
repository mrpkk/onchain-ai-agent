"""Тесты S3-01: Policy API — валидация, версионирование, ownership."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import database  # noqa: E402

VALID_YAML = """
version: 1
limits:
  per_tx_eth: 0.5
  daily_eth: 2.0
  velocity: {window_min: 10, max_tx: 3}
  gas_gwei_cap: 60
  slippage_bps_max: 50
deny:
  actions: [deploy]
approvals:
  required_if: {risk_score_gte: 0.6, amount_eth_gte: 0.25, new_spender: true}
"""

INVALID_YAML = "limits: {per_tx_eth: -5}"


@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    asyncio.run(database.drop_all())
    asyncio.run(database.create_all())
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client, username="policy-user") -> str:
    client.post("/api/v1/auth/register",
                json={"username": username, "password": "pass12345"})
    response = client.post("/api/v1/auth/token",
                           json={"username": username, "password": "pass12345"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _agent(client, token: str, name: str = "pol-agent") -> str:
    response = client.post("/api/v1/agents", json={"name": name},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 201
    return response.json()["id"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_policy_autocreated_from_tier(client):
    """S4-04: при создании агента автоматически выпускается политика его тира."""
    token = _auth(client)
    agent_id = _agent(client, token)
    response = client.get(f"/api/v1/agents/{agent_id}/policy", headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["compiled"]["model"]["limits"]["per_tx_eth"] == 0.1  # tier 0


def test_policy_put_and_get(client):
    token = _auth(client)
    agent_id = _agent(client, token)

    put = client.put(f"/api/v1/agents/{agent_id}/policy",
                     json={"dsl_yaml": VALID_YAML}, headers=_h(token))
    assert put.status_code == 200
    body = put.json()
    assert body["version"] == 2 and body["active"] is True  # v1 — авто-политика тира
    assert body["compiled"]["model"]["limits"]["per_tx_eth"] == 0.5
    assert body["compiled"]["model"]["deny"]["actions"] == ["deploy"]

    get = client.get(f"/api/v1/agents/{agent_id}/policy", headers=_h(token))
    assert get.status_code == 200
    assert get.json()["dsl_yaml"] == VALID_YAML


def test_policy_versioning_deactivates_previous(client):
    token = _auth(client)
    agent_id = _agent(client, token)

    client.put(f"/api/v1/agents/{agent_id}/policy",
               json={"dsl_yaml": VALID_YAML}, headers=_h(token))
    second_yaml = VALID_YAML.replace("per_tx_eth: 0.5", "per_tx_eth: 0.25")
    put2 = client.put(f"/api/v1/agents/{agent_id}/policy",
                      json={"dsl_yaml": second_yaml}, headers=_h(token))
    assert put2.status_code == 200
    assert put2.json()["version"] == 3

    active = client.get(f"/api/v1/agents/{agent_id}/policy", headers=_h(token))
    assert active.json()["version"] == 3
    assert active.json()["compiled"]["model"]["limits"]["per_tx_eth"] == 0.25

    async def _versions():
        import uuid as _uuid

        from src.db import PolicyRepository, session_scope
        async with session_scope() as session:
            return await PolicyRepository(session).list_versions(_uuid.UUID(agent_id))

    versions = asyncio.run(_versions())
    assert [(v.version, v.active) for v in versions] == [(3, True), (2, False), (1, False)]


def test_policy_invalid_rejected(client):
    token = _auth(client)
    agent_id = _agent(client, token)
    response = client.put(f"/api/v1/agents/{agent_id}/policy",
                          json={"dsl_yaml": INVALID_YAML}, headers=_h(token))
    assert response.status_code == 422
    assert "Invalid policy" in response.json()["detail"]


def test_validate_endpoint(client):
    token = _auth(client)
    ok = client.post("/api/v1/policies/validate",
                     json={"dsl_yaml": VALID_YAML}, headers=_h(token))
    assert ok.status_code == 200 and ok.json()["valid"] is True

    bad = client.post("/api/v1/policies/validate",
                      json={"dsl_yaml": INVALID_YAML}, headers=_h(token))
    assert bad.status_code == 200
    assert bad.json()["valid"] is False and bad.json()["errors"]


def test_policy_ownership_isolation(client):
    token_a = _auth(client, "owner-a")
    agent_id = _agent(client, token_a, "owned-agent")
    token_b = _auth(client, "owner-b")

    response = client.get(f"/api/v1/agents/{agent_id}/policy", headers=_h(token_b))
    assert response.status_code == 404
    put = client.put(f"/api/v1/agents/{agent_id}/policy",
                     json={"dsl_yaml": VALID_YAML}, headers=_h(token_b))
    assert put.status_code == 404
