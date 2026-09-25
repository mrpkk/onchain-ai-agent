"""Тесты S6-01: ERC-8004-реестр (бейджи, сервис с fake-контрактом, API, паспорт)."""

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
from src.integrations.agent_registry import AgentRegistryError, AgentRegistryService  # noqa: E402
from src.runtime.badges import compute_badges  # noqa: E402


# ── бейджи ───────────────────────────────────────────────────────────

def test_badges_full_set():
    badges = compute_badges(
        onchain={"agent_id": 3, "verified": True, "reputation": 87},
        health={"score": 100, "band": "healthy"},
        trust={"rung": "simulate"},
        tier=1,
    )
    ids = [b["id"] for b in badges]
    assert ids == ["onchain", "verified", "reputation", "health", "trust", "tier"]
    assert badges[0]["value"] == "#3"
    assert badges[2]["tone"] == "success"
    assert badges[3]["tone"] == "success"


def test_badges_tones_degrade():
    badges = compute_badges(
        onchain={"agent_id": 0, "verified": False, "reputation": 30},
        health={"score": 40, "band": "critical"},
        trust=None,
        tier=0,
    )
    by_id = {b["id"]: b for b in badges}
    assert by_id["reputation"]["tone"] == "danger"
    assert by_id["health"]["tone"] == "danger"
    assert "verified" not in by_id


def test_badges_minimal():
    badges = compute_badges(onchain=None, health=None, trust=None, tier=2)
    assert [b["id"] for b in badges] == ["tier"]


# ── сервис (fake-контракт) ───────────────────────────────────────────

class _Call:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def call(self, *args, **kwargs):
        if self.error:
            raise RuntimeError(self.error)
        return self.value


class FakeContract:
    def __init__(self, agent=(("bot", "uri", "0xOwner", 1, True, 87),), next_id=5, name_ids=None):
        self._agent = agent
        self._next = next_id
        self._name_ids = name_ids or {}
        self.functions = self

    def getAgent(self, agent_id):
        if agent_id >= len(self._agent):
            return _Call(error="execution reverted: AgentNotFound(5)")
        return _Call(self._agent[agent_id])

    def nextAgentId(self):
        return _Call(self._next)

    def resolveName(self, name):
        return _Call(self._name_ids.get(name, 0))


def _service(fake: FakeContract) -> AgentRegistryService:
    svc = AgentRegistryService(private_key="")
    svc._contract = fake
    return svc


def test_service_get_agent_mapping():
    svc = _service(FakeContract())
    data = asyncio.run(svc.get_agent(0))
    assert data["name"] == "bot"
    assert data["verified"] is True
    assert data["reputation"] == 87


def test_service_get_agent_not_found():
    svc = _service(FakeContract())
    with pytest.raises(AgentRegistryError) as err:
        asyncio.run(svc.get_agent(9))
    assert err.value.code == "NOT_FOUND"


def test_service_resolve_name():
    svc = _service(FakeContract(agent=(), name_ids={"taken": 2}))
    assert asyncio.run(svc.resolve_name("taken")) == 2
    assert asyncio.run(svc.resolve_name("free")) is None


def test_service_resolve_name_zero_disambiguation():
    """resolveName=0: агент #0 с этим именем — реальный id 0; иначе — не найдено."""
    svc = _service(FakeContract())  # agent #0 = ("bot", ...)
    assert asyncio.run(svc.resolve_name("bot")) == 0
    assert asyncio.run(svc.resolve_name("other")) is None


def test_service_send_requires_signer():
    svc = _service(FakeContract())
    with pytest.raises(AgentRegistryError) as err:
        svc._send("verifyAgent", [0])
    assert err.value.code == "SIGNER_MISSING"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _setup(client, username="reg"):
    client.post("/api/v1/auth/register", json={"username": username, "password": "reg-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "reg-pass-123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    agent = client.post("/api/v1/agents", json={"name": "reg-bot", "tier": 1}, headers=headers).json()
    return headers, agent


def test_registry_info_without_registration(client, monkeypatch):
    headers, agent = _setup(client, "reg_info")
    response = client.get(f"/api/v1/agents/{agent['id']}/registry", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["onchain"] is None
    ids = [b["id"] for b in body["badges"]]
    assert "health" in ids and "tier" in ids


def test_registry_register_and_conflict(client, monkeypatch):
    headers, agent = _setup(client, "reg_register")
    captured = {}

    async def fake_resolve(self, name):
        return None

    async def fake_register(self, name, metadata_uri):
        captured["name"] = name
        captured["uri"] = metadata_uri
        return {"tx_hash": "0xreg", "status": 1, "block": 1, "gas_used": 21000,
                "chain_id": 11155111, "agent_id": 0, "name": name}

    monkeypatch.setattr(AgentRegistryService, "resolve_name", fake_resolve)
    monkeypatch.setattr(AgentRegistryService, "register", fake_register)

    response = client.post(f"/api/v1/agents/{agent['id']}/registry", headers=headers)
    assert response.status_code == 201, response.text
    assert captured["name"] == "reg-bot"
    assert f"/api/v1/registry/agents/{agent['id']}/metadata" in captured["uri"]

    # повторная регистрация — 409
    assert client.post(f"/api/v1/agents/{agent['id']}/registry", headers=headers).status_code == 409

    # config сохранён — виден в списке агентов
    listed = client.get("/api/v1/agents", headers=headers).json()["agents"][0]
    assert listed["config"]["onchain"]["agent_id"] == 0


def test_registry_name_conflict_suffix(client, monkeypatch):
    headers, agent = _setup(client, "reg_suffix")
    captured = {}

    async def taken(self, name):
        return 1

    async def fake_register(self, name, metadata_uri):
        captured["name"] = name
        return {"tx_hash": "0x", "status": 1, "block": 1, "gas_used": 1,
                "chain_id": 11155111, "agent_id": 1, "name": name}

    monkeypatch.setattr(AgentRegistryService, "resolve_name", taken)
    monkeypatch.setattr(AgentRegistryService, "register", fake_register)

    assert client.post(f"/api/v1/agents/{agent['id']}/registry", headers=headers).status_code == 201
    assert captured["name"].startswith("reg-bot-")


def test_registry_verify_and_sync(client, monkeypatch):
    headers, agent = _setup(client, "reg_verify")

    async def fake_resolve(self, name):
        return None

    async def fake_register(self, name, metadata_uri):
        return {"tx_hash": "0x", "status": 1, "block": 1, "gas_used": 1,
                "chain_id": 11155111, "agent_id": 0, "name": name}

    monkeypatch.setattr(AgentRegistryService, "resolve_name", fake_resolve)
    monkeypatch.setattr(AgentRegistryService, "register", fake_register)
    client.post(f"/api/v1/agents/{agent['id']}/registry", headers=headers)

    async def fake_verify(self, agent_id):
        return {"tx_hash": "0xv", "status": 1, "block": 2, "gas_used": 1, "chain_id": 11155111}

    monkeypatch.setattr(AgentRegistryService, "verify", fake_verify)
    response = client.post(f"/api/v1/agents/{agent['id']}/registry/verify", headers=headers)
    assert response.status_code == 200
    listed = client.get("/api/v1/agents", headers=headers).json()["agents"][0]
    assert listed["config"]["onchain"]["verified"] is True

    async def fake_rep(self, agent_id, score):
        assert 0 <= score <= 100
        return {"tx_hash": "0xr", "status": 1, "block": 3, "gas_used": 1, "chain_id": 11155111}

    monkeypatch.setattr(AgentRegistryService, "set_reputation", fake_rep)
    response = client.post(
        f"/api/v1/agents/{agent['id']}/registry/sync-reputation", headers=headers
    )
    assert response.status_code == 200
    assert 0 <= response.json()["score"] <= 100


def test_registry_verify_requires_registration(client):
    headers, agent = _setup(client, "reg_verify_no")
    response = client.post(f"/api/v1/agents/{agent['id']}/registry/verify", headers=headers)
    assert response.status_code == 409


def test_public_metadata_passport(client):
    headers, agent = _setup(client, "reg_public")

    response = client.get(f"/api/v1/registry/agents/{agent['id']}/metadata")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "reg-bot"
    assert body["karta"]["tier"] == 1
    assert "reg_public" not in response.text  # владелец не утекает

    assert client.get("/api/v1/registry/agents/not-a-uuid/metadata").status_code == 404
