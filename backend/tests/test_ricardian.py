"""Тесты S6-03: Ricardian-сервис (fake-контракт) и API (mapped errors, auth)."""

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
from src.integrations.ricardian import RicardianError, RicardianService  # noqa: E402


# ── fake-слой (без сети) ─────────────────────────────────────────────

class _Call:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def call(self, *args, **kwargs):
        if self.error:
            raise RuntimeError(self.error)
        return self.value


class FakeContract:
    """Мини-фейк: functions.* возвращают _Call."""

    def __init__(self, next_id=0, agreements=None, milestones=None):
        self._next = next_id
        self._agreements = agreements or {}
        self._milestones = milestones or {}
        self.functions = self

    def nextAgreementId(self):
        return _Call(self._next)

    def getAgreement(self, agreement_id):
        return _Call(self._agreements[agreement_id])

    def getMilestone(self, agreement_id, index):
        return _Call(self._milestones[(agreement_id, index)])


class FakeEth:
    def __init__(self, chain_id):
        self.chain_id = chain_id


class FakeW3:
    def __init__(self, chain_id):
        self.eth = FakeEth(chain_id)


def _service_with_fake_contract() -> RicardianService:
    svc = RicardianService(private_key="")
    svc._contract = FakeContract(
        next_id=2,
        agreements={
            0: (b"\x11" * 32, ["0xAAA", "0xBBB", "0xCCC"], "0xToken", 1000, 2, 0, 0),
            1: (b"\x22" * 32, ["0xAAA", "0xBBB", "0xCCC"], "0xToken", 2000, 1, 2, 2),
        },
        milestones={
            (0, 0): ("Design", 400, 1_800_000_000, False, False),
            (0, 1): ("Build", 600, 1_800_100_000, True, False),
            (1, 0): ("Audit", 2000, 1_800_200_000, False, True),
        },
    )
    return svc


# ── сервис: guards ───────────────────────────────────────────────────

def test_connect_forbids_mainnet():
    svc = RicardianService(private_key="")
    svc._w3 = FakeW3(chain_id=1)
    with pytest.raises(RicardianError) as err:
        svc._connect()
    assert err.value.code == "MAINNET_FORBIDDEN"


def test_connect_requires_contract_address():
    svc = RicardianService(private_key="", contract_address="")
    svc._w3 = FakeW3(chain_id=11155111)
    with pytest.raises(RicardianError) as err:
        svc._connect()
    assert err.value.code == "NOT_CONFIGURED"


def test_send_requires_signer_key():
    svc = _service_with_fake_contract()
    with pytest.raises(RicardianError) as err:
        svc._send("signAgreement", [1])
    assert err.value.code == "SIGNER_MISSING"


# ── сервис: чтение ───────────────────────────────────────────────────

def test_list_and_get_agreements_mapping():
    import asyncio

    svc = _service_with_fake_contract()
    agreements = asyncio.run(svc.list_agreements())
    assert [a["id"] for a in agreements] == [1, 0]  # свежие первыми
    first = agreements[1]
    assert first["status"] == "draft"
    assert first["sign_count"] == 0
    assert first["milestones"][1]["completed"] is True
    second = agreements[0]
    assert second["status"] == "active"
    assert second["milestones"][0]["disputed"] is True

    detail = asyncio.run(svc.get_agreement(0))
    assert detail["total_amount_wei"] == "1000"
    assert len(detail["parties"]) == 3


def test_get_agreement_not_found():
    import asyncio

    svc = _service_with_fake_contract()
    with pytest.raises(RicardianError) as err:
        asyncio.run(svc.get_agreement(99))
    assert err.value.code == "NOT_FOUND"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client, username="ric"):
    client.post("/api/v1/auth/register", json={"username": username, "password": "ric-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "ric-pass-123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_requires_auth(client):
    assert client.get("/api/v1/ricardian/agreements").status_code == 401


def test_api_list_ok(client, monkeypatch):
    headers = _auth(client, "ric_list")

    async def fake_list(self, limit=20):
        return [{"id": 0, "status": "draft", "sign_count": 0, "milestones": []}]

    monkeypatch.setattr(RicardianService, "list_agreements", fake_list)
    response = client.get("/api/v1/ricardian/agreements", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_api_create_ok(client, monkeypatch):
    headers = _auth(client, "ric_create")

    async def fake_create(self, parties, token, milestones, agreement_hash=None):
        assert milestones[0]["description"] == "Design"
        return {"tx_hash": "0xabc", "status": 1, "block": 1, "gas_used": 21000,
                "agreement_id": 0, "agreement_hash": "0x" + "11" * 32}

    monkeypatch.setattr(RicardianService, "create_agreement", fake_create)
    response = client.post(
        "/api/v1/ricardian/agreements",
        json={"parties": ["0xAAA", "0xBBB"], "token": "0xToken",
              "milestones": [{"description": "Design", "amount_wei": "100",
                              "deadline": 1800000000}]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["agreement_id"] == 0


def test_api_error_mapping(client, monkeypatch):
    headers = _auth(client, "ric_err")

    async def not_found(self, agreement_id):
        raise RicardianError("NOT_FOUND", "нет")

    monkeypatch.setattr(RicardianService, "get_agreement", not_found)
    assert client.get("/api/v1/ricardian/agreements/9", headers=headers).status_code == 404

    async def mainnet(self, *args, **kwargs):
        raise RicardianError("MAINNET_FORBIDDEN", "нельзя")

    monkeypatch.setattr(RicardianService, "list_agreements", mainnet)
    assert client.get("/api/v1/ricardian/agreements", headers=headers).status_code == 403

    async def revert(self, agreement_id):
        raise RicardianError("SIMULATION_REVERT", "revert")

    monkeypatch.setattr(RicardianService, "sign", revert)
    assert client.post("/api/v1/ricardian/agreements/0/sign", headers=headers).status_code == 422

    async def no_key(self, agreement_id, index):
        raise RicardianError("SIGNER_MISSING", "нет ключа")

    monkeypatch.setattr(RicardianService, "dispute_milestone", no_key)
    response = client.post("/api/v1/ricardian/agreements/0/milestones/0/dispute", headers=headers)
    assert response.status_code == 503


def test_api_wallet(client):
    headers = _auth(client, "ric_wallet")
    response = client.get("/api/v1/ricardian/wallet", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["chain"] == "sepolia"
    assert "signer" in body
