"""Тесты S5-02: bridge-сервис (LI.FI-котировка, статус, gated-исполнение) и API."""

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import database  # noqa: E402
from src.integrations.bridge import BridgeError, BridgeService  # noqa: E402

LI_FI_QUOTE = {
    "id": "route-1",
    "tool": "across",
    "toolDetails": {"name": "AcrossV4"},
    "action": {
        "fromChainId": 1, "toChainId": 8453,
        "fromToken": {"address": "0xEeee"}, "toToken": {"address": "0xEeee"},
        "fromAmount": "10000000000000000",
    },
    "estimate": {
        "toAmount": "9972127913823374",
        "toAmountMin": "9922268774253757",
        "executionDuration": 2,
        "feeCosts": [{"name": "LIFI Fixed Fee", "amountUSD": "0.0674"}],
        "gasCosts": [{"type": "SEND", "amountUSD": "0.05"}],
    },
    "transactionRequest": {
        "to": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
        "data": "0x1794958f00",
        "value": "0x2386f26fc10000",
        "gasLimit": "0x82208",
        "chainId": 1,
    },
}


def _service(handler, **kwargs) -> BridgeService:
    transport = httpx.MockTransport(handler)
    return BridgeService(
        provider_url="https://li.quest/v1", transport=transport,
        private_key=kwargs.pop("private_key", ""), **kwargs,
    )


def test_quote_normalization():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/quote"
        assert request.url.params["fromChain"] == "1"
        return httpx.Response(200, json=LI_FI_QUOTE)

    svc = _service(handler)
    quote = asyncio.run(svc.quote(1, 8453, 10**16, from_address="0xabc"))
    assert quote["tool"] == "across" and quote["tool_name"] == "AcrossV4"
    assert quote["to_amount"] == "9972127913823374"
    assert quote["execution_seconds"] == 2
    assert quote["fee_usd_total"] == pytest.approx(0.0674)
    assert quote["transaction_request"]["to"].startswith("0x1231")


def test_quote_no_route():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "message": "No available quotes",
            "code": 1002,
            "errors": {"filteredOut": [{"reason": "no liquidity"}]},
        })

    svc = _service(handler)
    with pytest.raises(BridgeError) as err:
        asyncio.run(svc.quote(11155111, 84532, 10**16, from_address="0xabc"))
    assert err.value.code == "NO_ROUTE"


def test_quote_provider_errors():
    def handler_500(request):
        return httpx.Response(500, text="boom")

    with pytest.raises(BridgeError) as err:
        asyncio.run(_service(handler_500).quote(1, 8453, 10**16, from_address="0xabc"))
    assert err.value.code == "BRIDGE_ERROR"

    def handler_net(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(BridgeError) as err:
        asyncio.run(_service(handler_net).quote(1, 8453, 10**16, from_address="0xabc"))
    assert err.value.code == "BRIDGE_UNAVAILABLE"


def test_quote_validation():
    svc = _service(lambda r: httpx.Response(200, json={}))
    with pytest.raises(BridgeError) as err:
        asyncio.run(svc.quote(1, 1, 10**16, from_address="0xabc"))
    assert err.value.code == "BAD_INPUT"
    with pytest.raises(BridgeError) as err:
        asyncio.run(svc.quote(1, 8453, 0, from_address="0xabc"))
    assert err.value.code == "BAD_INPUT"


def test_status_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/status"
        return httpx.Response(200, json={
            "status": "DONE", "substatus": "COMPLETED", "tool": "across",
            "sending": {"txHash": "0xs"}, "receiving": {"txHash": "0xr"},
        })

    svc = _service(handler)
    status = asyncio.run(svc.status("0xabc", 1, 8453))
    assert status["status"] == "DONE" and status["receiving"] == "0xr"


def test_execute_gated_by_default():
    svc = _service(lambda r: httpx.Response(200, json={}))
    with pytest.raises(BridgeError) as err:
        svc.execute_sync({"transaction_request": LI_FI_QUOTE["transactionRequest"]})
    assert err.value.code == "EXECUTION_DISABLED"


def test_execute_forbids_mainnet_when_enabled():
    svc = _service(lambda r: httpx.Response(200, json={}),
                   execution_enabled=True, private_key="0x" + "11" * 32)
    with pytest.raises(BridgeError) as err:
        svc.execute_sync({"transaction_request": LI_FI_QUOTE["transactionRequest"]})
    assert err.value.code == "MAINNET_FORBIDDEN"


def test_execute_requires_signer():
    svc = _service(lambda r: httpx.Response(200, json={}), execution_enabled=True)
    quote = {"transaction_request": {**LI_FI_QUOTE["transactionRequest"], "chainId": 11155111}}
    with pytest.raises(BridgeError) as err:
        svc.execute_sync(quote)
    assert err.value.code == "SIGNER_MISSING"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client, username="bridge"):
    client.post("/api/v1/auth/register", json={"username": username, "password": "br-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "br-pass-123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_requires_auth(client):
    assert client.get("/api/v1/bridge/info").status_code == 401


def test_api_quote_and_gated_execute(client, monkeypatch):
    headers = _auth(client)

    async def fake_quote(self, from_chain, to_chain, amount_wei, **kwargs):
        return {"route_id": "r1", "tool": "across", "tool_name": "AcrossV4",
                "from_chain": from_chain, "to_chain": to_chain,
                "to_amount": "9972127913823374", "execution_seconds": 2,
                "fees": [], "fee_usd_total": 0.07, "transaction_request": {"to": "0x1"},
                "source": "lifi"}

    monkeypatch.setattr(BridgeService, "quote", fake_quote)
    response = client.get(
        "/api/v1/bridge/quote?from_chain=1&to_chain=8453&amount=10000000000000000",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["tool_name"] == "AcrossV4"

    async def fake_execute(self, quote):
        raise BridgeError("EXECUTION_DISABLED", "выключено")

    monkeypatch.setattr(BridgeService, "execute", fake_execute)
    response = client.post("/api/v1/bridge/execute", json={"quote": {}}, headers=headers)
    assert response.status_code == 403

    async def fake_quote_no_route(self, *args, **kwargs):
        raise BridgeError("NO_ROUTE", "нет маршрута")

    monkeypatch.setattr(BridgeService, "quote", fake_quote_no_route)
    response = client.get(
        "/api/v1/bridge/quote?from_chain=1&to_chain=8453&amount=10000000000000000",
        headers=headers,
    )
    assert response.status_code == 422


def test_api_info_shape(client):
    headers = _auth(client, "bridge_info")
    body = client.get("/api/v1/bridge/info", headers=headers).json()
    assert body["execution_enabled"] is False
    assert body["provider"].startswith("https://li.quest")
    assert 8453 in body["supported_chains"]
