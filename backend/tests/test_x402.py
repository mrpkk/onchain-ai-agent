"""Тесты S6-05: x402-демо (402-челлендж, EIP-3009-верификация, API-флоу).

Сеть не нужна: verify — локальный (ecrecover), settle — monkeypatch.
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_typed_data  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from web3 import Web3  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import database  # noqa: E402
from src.integrations.x402 import (  # noqa: E402
    ASSET_NAME,
    ASSET_VERSION,
    NETWORK,
    X402Error,
    X402Service,
)

PAY_TO = "0xE14264bb1F24a5C95A620E00CE02d793daa12Cd2"
TOKEN = "0x0eB3e17862A108Bbbc91989e6Ca1a3ed16f69710"
PAYER_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"  # anvil #2 (тест)
PAYER = Account.from_key(PAYER_KEY).address
PRICE = 10**16


class FakeEth:
    chain_id = 11155111


class FakeW3:
    eth = FakeEth()
    to_checksum_address = staticmethod(Web3.to_checksum_address)


class TestX402Service(X402Service):
    """Сервис без сети: _connect — no-op, settle — подменяется в тестах."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token = object()
        self._w3 = FakeW3()

    @property
    def pay_to(self):
        return PAY_TO


def make_payment_header(*, value=PRICE, to=PAY_TO, valid_after=None, valid_before=None,
                        signer_key=PAYER_KEY, nonce=None):
    now = int(time.time())
    authorization = {
        "from": Account.from_key(signer_key).address,
        "to": to,
        "value": str(value),
        "validAfter": str(0 if valid_after is None else valid_after),
        "validBefore": str(now + 300 if valid_before is None else valid_before),
        "nonce": nonce or ("0x" + "11" * 32),
    }
    domain = {"name": ASSET_NAME, "version": ASSET_VERSION, "chainId": 11155111,
              "verifyingContract": TOKEN}
    types = {
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ]
    }
    message = {
        "from": authorization["from"], "to": authorization["to"],
        "value": int(authorization["value"]),
        "validAfter": int(authorization["validAfter"]),
        "validBefore": int(authorization["validBefore"]),
        "nonce": authorization["nonce"],
    }
    encoded = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
    signed = Account.sign_message(encoded, private_key=signer_key)
    payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": NETWORK,
        "payload": {"signature": signed.signature.hex(), "authorization": authorization},
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


# ── сервис ───────────────────────────────────────────────────────────

def test_requirements_shape():
    svc = TestX402Service()
    req = svc.payment_requirements("http://127.0.0.1:8090/api/v1/x402/demo/premium")
    assert req["x402Version"] == 1
    accept = req["accepts"][0]
    assert accept["scheme"] == "exact" and accept["network"] == "sepolia"
    assert accept["payTo"] == PAY_TO and accept["asset"] == TOKEN
    assert accept["maxAmountRequired"] == str(PRICE)
    assert req["demo"] is True


def test_verify_valid_payment():
    svc = TestX402Service()
    payment = svc.verify_payment(make_payment_header())
    assert payment["from"] == PAYER
    assert payment["value"] == PRICE


def test_verify_rejects_bad_signature():
    svc = TestX402Service()
    header = make_payment_header(signer_key=PAYER_KEY)
    payload = json.loads(base64.b64decode(header))
    payload["payload"]["authorization"]["from"] = "0x" + "22" * 20  # чужой from
    tampered = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(X402Error) as err:
        svc.verify_payment(tampered)
    assert err.value.code == "BAD_SIGNATURE"


def test_verify_rejects_insufficient_and_payee_and_expired():
    svc = TestX402Service()
    with pytest.raises(X402Error) as err:
        svc.verify_payment(make_payment_header(value=PRICE - 1))
    assert err.value.code == "INSUFFICIENT"

    with pytest.raises(X402Error) as err:
        svc.verify_payment(make_payment_header(to="0x" + "33" * 20))
    assert err.value.code == "WRONG_PAYEE"

    with pytest.raises(X402Error) as err:
        svc.verify_payment(make_payment_header(valid_before=int(time.time()) - 10))
    assert err.value.code == "EXPIRED"


def test_verify_rejects_garbage_header():
    svc = TestX402Service()
    with pytest.raises(X402Error) as err:
        svc.verify_payment("not-base64!!")
    assert err.value.code == "INVALID_PAYMENT"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    from src.api import main as main_module

    monkeypatch.setattr(main_module, "X402Service", TestX402Service)
    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_api_402_challenge(client):
    response = client.get("/api/v1/x402/demo/premium")
    assert response.status_code == 402
    body = response.json()
    assert body["accepts"][0]["payTo"] == PAY_TO
    assert body["demo"] is True


def test_api_paid_flow(client, monkeypatch):
    async def fake_settle(self, header):
        return {"tx_hash": "0xdead", "block": 1, "gas_used": 21000, "network": "sepolia",
                "payer": PAYER, "amount_wei": str(PRICE)}

    monkeypatch.setattr(TestX402Service, "verify_and_settle", fake_settle)
    response = client.get(
        "/api/v1/x402/demo/premium",
        headers={"X-PAYMENT": make_payment_header()},
    )
    assert response.status_code == 200, response.text
    assert "X-PAYMENT-RESPONSE" in response.headers
    receipt = json.loads(base64.b64decode(response.headers["X-PAYMENT-RESPONSE"]))
    assert receipt["tx_hash"] == "0xdead"
    assert response.json()["paid_by"] == PAYER


def test_api_rejects_replay(client, monkeypatch):
    async def replay(self, header):
        raise X402Error("NONCE_USED", "Эта авторизация уже использована")

    monkeypatch.setattr(TestX402Service, "verify_and_settle", replay)
    response = client.get(
        "/api/v1/x402/demo/premium",
        headers={"X-PAYMENT": make_payment_header()},
    )
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "NONCE_USED"
