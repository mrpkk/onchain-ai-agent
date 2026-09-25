"""Тесты S5-06: ERC-4337-сервис (session keys, userOp, guards) и API."""

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
from src.integrations.erc4337 import AAError, ERC4337Service  # noqa: E402

OWNER_KEY = "0x" + "11" * 32
SESSION_KEY = "0x" + "22" * 32


def _service(**kwargs) -> ERC4337Service:
    return ERC4337Service(rpc_url="http://127.0.0.1:1", entrypoint="0xEP", account="0xACC",
                          owner_key=OWNER_KEY, session_key=SESSION_KEY, **kwargs)


def test_owner_and_session_addresses():
    svc = _service()
    assert svc.owner_address and svc.owner_address.startswith("0x")
    assert svc.session_key_address and svc.session_key_address != svc.owner_address


def test_send_requires_signer(monkeypatch):
    svc = ERC4337Service(rpc_url="http://127.0.0.1:1", entrypoint="0xEP", account="0xACC",
                         owner_key="", session_key="")
    # _connect без сети не пройдёт — подменяем на no-op и подсовываем фейковый w3
    monkeypatch.setattr(svc, "_connect", lambda: None)
    svc._w3 = type("W", (), {"eth": type("E", (), {"chain_id": 11155111})()})()
    with pytest.raises(AAError) as err:
        svc._send(object())
    assert err.value.code == "SIGNER_MISSING"


def test_mainnet_forbidden():
    svc = _service()
    svc._w3 = type("W", (), {"eth": type("E", (), {"chain_id": 1})()})()
    with pytest.raises(AAError) as err:
        svc._connect()
    assert err.value.code == "MAINNET_FORBIDDEN"


def test_not_configured_without_account(monkeypatch):
    import asyncio

    svc = ERC4337Service(rpc_url="http://127.0.0.1:1", entrypoint="0xEP", account="",
                         owner_key=OWNER_KEY, session_key=SESSION_KEY)
    monkeypatch.setattr(svc, "_connect", lambda: None)
    with pytest.raises(AAError) as err:
        asyncio.run(svc.add_session_key("0x" + "33" * 20, 0, 100))
    assert err.value.code == "NOT_CONFIGURED"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client, username="aa_user"):
    client.post("/api/v1/auth/register", json={"username": username, "password": "aa-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "aa-pass-123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_requires_auth(client):
    assert client.get("/api/v1/erc4337/info").status_code == 401


def test_api_info_shape(client, monkeypatch):
    headers = _auth(client)

    async def fake_info(self):
        return {"entrypoint": "0xEP", "account": "0xACC", "owner": "0xOWNER",
                "session_key_configured": True, "chain": "sepolia", "nonce": 3}

    monkeypatch.setattr(ERC4337Service, "info", fake_info)
    body = client.get("/api/v1/erc4337/info", headers=headers).json()
    assert body["nonce"] == 3 and body["session_key_configured"] is True


def test_api_session_key_and_userop_flow(client, monkeypatch):
    headers = _auth(client, "aa_flow")

    async def fake_add(self, key_address, valid_until, spend_limit_wei, allowed_target=""):
        return {"tx_hash": "0xadd", "status": 1, "block": 1, "gas_used": 1, "chain_id": 11155111}

    monkeypatch.setattr(ERC4337Service, "add_session_key", fake_add)
    response = client.post("/api/v1/erc4337/session-keys",
                           json={"key_address": "0x" + "44" * 20, "spend_limit_wei": "1000"},
                           headers=headers)
    assert response.status_code == 201

    async def fake_revoke(self, key_address):
        return {"tx_hash": "0xrev", "status": 1, "block": 2, "gas_used": 1, "chain_id": 11155111}

    monkeypatch.setattr(ERC4337Service, "revoke_session_key", fake_revoke)
    assert client.delete("/api/v1/erc4337/session-keys/0x" + "44" * 20,
                         headers=headers).status_code == 200

    async def fake_exec(self, target, value=0, data="0x", use_session_key=False):
        return {"tx_hash": "0xop", "status": 1, "block": 3, "gas_used": 1,
                "chain_id": 11155111, "via_session_key": use_session_key}

    monkeypatch.setattr(ERC4337Service, "execute_user_op", fake_exec)
    response = client.post("/api/v1/erc4337/userop",
                           json={"target": "0x" + "55" * 20, "use_session_key": True},
                           headers=headers)
    assert response.status_code == 200
    assert response.json()["via_session_key"] is True


def test_api_error_mapping(client, monkeypatch):
    headers = _auth(client, "aa_err")

    async def forbidden(self):
        raise AAError("MAINNET_FORBIDDEN", "нельзя")

    monkeypatch.setattr(ERC4337Service, "info", forbidden)
    assert client.get("/api/v1/erc4337/info", headers=headers).status_code == 403

    async def revert(self, target, value=0, data="0x", use_session_key=False):
        raise AAError("SIMULATION_REVERT", "revert")

    monkeypatch.setattr(ERC4337Service, "execute_user_op", revert)
    response = client.post("/api/v1/erc4337/userop",
                           json={"target": "0x" + "55" * 20}, headers=headers)
    assert response.status_code == 422


# ── Внутренние пути (fake-контракты, без сети) ───────────────────────

from types import SimpleNamespace  # noqa: E402


class _Fn:
    def __init__(self, result=None):
        self._result = result

    def call(self, *args, **kwargs):
        return self._result

    def build_transaction(self, tx):
        return dict(tx)


class _FakeEth:
    chain_id = 11155111

    class _AccountObj:
        @staticmethod
        def sign_transaction(tx, private_key):
            return SimpleNamespace(raw_transaction=b"raw")

    account = _AccountObj()

    def get_transaction_count(self, addr, *args):
        return 7

    def send_raw_transaction(self, raw):
        return b"\xaa\xbb"

    def wait_for_transaction_receipt(self, tx_hash, timeout=0):
        return SimpleNamespace(status=1, blockNumber=9, gasUsed=50000)


class _FakeW3:
    def __init__(self):
        self.eth = _FakeEth()

    @staticmethod
    def to_checksum_address(address):
        return address


class _FakeEp:
    def __init__(self):
        self.functions = self

    def getUserOpHash(self, op):
        return _Fn(b"\x11" * 32)

    def handleOps(self, ops, beneficiary):
        return _Fn()


class _FakeAccountContract:
    def __init__(self, nonce=5):
        self.functions = self
        self._nonce = nonce

    def getNonce(self):
        return _Fn(self._nonce)

    def addSessionKey(self, *args):
        return _Fn()

    def revokeSessionKey(self, *args):
        return _Fn()

    def addGuardian(self, *args):
        return _Fn()

    def owner(self):
        return _Fn("0x" + "ab" * 20)

    def guardians(self, index):
        if index == 0:
            return _Fn("0x" + "cd" * 20)
        raise Exception("out of range")


def _fake_service(**kwargs) -> ERC4337Service:
    svc = ERC4337Service(entrypoint="0xEP", account="0xACC",
                         owner_key=OWNER_KEY, session_key=SESSION_KEY, **kwargs)
    svc._w3 = _FakeW3()
    svc._ep = _FakeEp()
    svc._account = _FakeAccountContract()
    return svc


def test_userop_build_sign_and_handleops_fake():
    svc = _fake_service()
    result = svc._build_and_execute_sync("0x" + "55" * 20, 0, "0x", use_session_key=True)
    assert result["status"] == 1 and result["nonce"] == 5
    assert result["via_session_key"] is True
    assert result["signer"] == svc.session_key_address

    owner_result = svc._build_and_execute_sync("0x" + "55" * 20, 0, "0x", use_session_key=False)
    assert owner_result["via_session_key"] is False


def test_owner_writes_fake():
    import asyncio

    svc = _fake_service()
    add = asyncio.run(svc.add_session_key("0x" + "33" * 20, 0, 100))
    assert add["status"] == 1 and add["tx_hash"]
    assert asyncio.run(svc.revoke_session_key("0x" + "33" * 20))["status"] == 1
    assert asyncio.run(svc.add_guardian("0x" + "44" * 20))["status"] == 1


def test_info_reads_fake_contract():
    import asyncio

    svc = _fake_service()
    info = asyncio.run(svc.info())
    assert info["account_owner"] == "0x" + "ab" * 20
    assert info["nonce"] == 5
    assert info["guardians"] == ["0x" + "cd" * 20]
