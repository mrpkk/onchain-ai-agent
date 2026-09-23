"""Тесты S6-02: Escrow-аренда (сервис с fake-контрактом, API, аренда агента)."""

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
from src.integrations.escrow import EscrowError, EscrowService  # noqa: E402


class _Call:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def call(self, *args, **kwargs):
        if self.error:
            raise RuntimeError(self.error)
        return self.value


class FakeContract:
    def __init__(self, escrows=None, next_id=0):
        self._escrows = escrows or {}
        self._next = next_id
        self.functions = self

    def nextEscrowId(self):
        return _Call(self._next)

    def getEscrow(self, escrow_id):
        return _Call(self._escrows[escrow_id])


def _service(fake: FakeContract) -> EscrowService:
    svc = EscrowService(private_key="")
    svc._contract = fake
    return svc


def test_service_escrow_statuses():
    fake = FakeContract(
        next_id=3,
        escrows={
            0: ("0xPayer", "0xPayee", 1000, "0xToken", False, False, False, "0xArb"),
            1: ("0xPayer", "0xPayee", 2000, "0xToken", True, False, False, "0xArb"),
            2: ("0xPayer", "0xPayee", 3000, "0xToken", False, False, True, "0xArb"),
        },
    )
    svc = _service(fake)
    escrows = asyncio.run(svc.list_recent())
    assert [e["id"] for e in escrows] == [2, 1, 0]
    assert [e["status"] for e in escrows] == ["disputed", "released", "locked"]
    assert escrows[2]["amount_wei"] == "1000"


def test_service_get_not_found():
    svc = _service(FakeContract(next_id=1, escrows={0: ("0xP", "0xQ", 1, "0xT", False, False, False, "0xA")}))
    with pytest.raises(EscrowError) as err:
        asyncio.run(svc.get_escrow(5))
    assert err.value.code == "NOT_FOUND"


def test_service_send_requires_signer():
    svc = _service(FakeContract())
    with pytest.raises(EscrowError) as err:
        svc._send("release", [0])
    assert err.value.code == "SIGNER_MISSING"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _setup(client, username="esc", with_wallet=False):
    client.post("/api/v1/auth/register", json={"username": username, "password": "esc-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "esc-pass-123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"name": "esc-bot", "tier": 1}
    if with_wallet:
        payload["wallet_address"] = "0xAgentWallet000000000000000000000000000001"
    agent = client.post("/api/v1/agents", json=payload, headers=headers).json()
    return headers, agent


def test_escrow_requires_auth(client):
    assert client.get("/api/v1/escrow").status_code == 401


def test_escrow_create_with_agent_payee(client, monkeypatch):
    headers, agent = _setup(client, "esc_agent", with_wallet=True)
    captured = {}

    async def fake_create(self, payee, amount_wei, token_address=None):
        captured["payee"] = payee
        captured["amount"] = amount_wei
        return {"tx_hash": "0xe", "status": 1, "block": 1, "gas_used": 1,
                "chain_id": 11155111, "escrow_id": 0, "payee": payee,
                "amount_wei": str(amount_wei), "approve_tx": "0xa"}

    monkeypatch.setattr(EscrowService, "create_rental", fake_create)
    response = client.post(
        "/api/v1/escrow",
        json={"amount_wei": "1000", "agent_id": agent["id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert captured["payee"] == "0xAgentWallet000000000000000000000000000001"
    assert captured["amount"] == 1000
    assert response.json()["approve_tx"] == "0xa"


def test_escrow_agent_without_wallet_conflict(client):
    headers, agent = _setup(client, "esc_nowallet", with_wallet=False)
    response = client.post(
        "/api/v1/escrow",
        json={"amount_wei": "1000", "agent_id": agent["id"]},
        headers=headers,
    )
    assert response.status_code == 409


def test_escrow_create_validation(client):
    headers, _ = _setup(client, "esc_val")
    assert client.post("/api/v1/escrow", json={"amount_wei": "10"}, headers=headers).status_code == 422
    assert client.post(
        "/api/v1/escrow", json={"amount_wei": "abc", "payee": "0x1"}, headers=headers
    ).status_code == 422
    assert client.post(
        "/api/v1/escrow", json={"amount_wei": "0", "payee": "0x1"}, headers=headers
    ).status_code == 422


def test_escrow_actions_and_error_mapping(client, monkeypatch):
    headers, _ = _setup(client, "esc_actions")

    async def fake_tx(self, escrow_id, *args):
        return {"tx_hash": "0x", "status": 1, "block": 1, "gas_used": 1, "chain_id": 11155111}

    monkeypatch.setattr(EscrowService, "release", lambda self, i: fake_tx(self, i))
    monkeypatch.setattr(EscrowService, "refund", lambda self, i: fake_tx(self, i))
    monkeypatch.setattr(EscrowService, "dispute", lambda self, i: fake_tx(self, i))

    assert client.post("/api/v1/escrow/0/release", headers=headers).status_code == 200
    assert client.post("/api/v1/escrow/0/refund", headers=headers).status_code == 200
    assert client.post("/api/v1/escrow/0/dispute", headers=headers).status_code == 200

    async def fake_resolve(self, escrow_id, release_to_payee):
        return {"tx_hash": "0x", "status": 1, "block": 1, "gas_used": 1,
                "chain_id": 11155111, "release_to_payee": release_to_payee}

    monkeypatch.setattr(EscrowService, "resolve", fake_resolve)
    response = client.post(
        "/api/v1/escrow/0/resolve", json={"release_to_payee": True}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["release_to_payee"] is True

    async def forbidden(self, limit=20):
        raise EscrowError("MAINNET_FORBIDDEN", "нельзя")

    monkeypatch.setattr(EscrowService, "list_recent", forbidden)
    assert client.get("/api/v1/escrow", headers=headers).status_code == 403

    async def no_key(self, escrow_id):
        raise EscrowError("SIGNER_MISSING", "нет ключа")

    monkeypatch.setattr(EscrowService, "release", no_key)
    assert client.post("/api/v1/escrow/0/release", headers=headers).status_code == 503


def test_escrow_wallet_endpoint(client):
    headers, _ = _setup(client, "esc_wallet")
    response = client.get("/api/v1/escrow/wallet", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["chain"] == "sepolia"
    assert "token_balance" in body
