"""Тесты S5-01: swap-сервис (котировка, slippage-guard, кап) и API."""

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
from src.integrations.swap import SwapError, SwapService  # noqa: E402

TOKEN_A = "0x212774d426519437d5Eb1126fE382fC7b7cCe7B0"
TOKEN_B = "0x0eB3e17862A108Bbbc91989e6Ca1a3ed16f69710"


class _Call:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def call(self, *args, **kwargs):
        if self.error:
            raise RuntimeError(self.error)
        return self.value


class FakeDex:
    """Пул 1:1 с комиссией 0.30% (как MockDEX)."""

    def __init__(self, reserve0=10**22, reserve1=10**22):
        self.r0, self.r1 = reserve0, reserve1
        self.functions = self

    def token0(self):
        return _Call(TOKEN_A)

    def reserve0(self):
        return _Call(self.r0)

    def reserve1(self):
        return _Call(self.r1)

    def getAmountsOut(self, amount_in, path):
        in_with_fee = amount_in * 9970
        out = in_with_fee * self.r1 // (self.r0 * 10000 + in_with_fee)
        return _Call([amount_in, out])


def _service(fake: FakeDex) -> SwapService:
    svc = SwapService(private_key="", router_address="0xDEX")
    svc._dex = fake
    svc._w3 = None
    # для котировки нужен только dex; _connect вернётся сразу (dex задан)
    return svc


def test_quote_math_and_min_out():
    import asyncio

    svc = _service(FakeDex())
    quote = asyncio.run(svc.quote(10**18, slippage_bps=50))
    assert int(quote["amount_out"]) < 10**18  # комиссия
    assert int(quote["min_amount_out"]) == int(quote["amount_out"]) * 9950 // 10000
    assert quote["slippage_bps"] == 50
    assert quote["price_impact_bps"] >= 0
    assert quote["source"].startswith("mockdex")


def test_quote_bad_input():
    import asyncio

    svc = _service(FakeDex())
    with pytest.raises(SwapError) as err:
        asyncio.run(svc.quote(0))
    assert err.value.code == "BAD_INPUT"
    with pytest.raises(SwapError) as err:
        asyncio.run(svc.quote(10**18, slippage_bps=20000))
    assert err.value.code == "BAD_INPUT"


def test_execute_refuses_above_slippage_cap():
    import asyncio

    svc = _service(FakeDex())
    with pytest.raises(SwapError) as err:
        asyncio.run(svc.execute(10**18, slippage_bps=100, max_slippage_bps=50))
    assert err.value.code == "SLIPPAGE_CAP_EXCEEDED"


def test_aggregator_unavailable_honest():
    import asyncio

    svc = _service(FakeDex())
    with pytest.raises(SwapError) as err:
        asyncio.run(svc.aggregator_quote(10**18))
    assert err.value.code == "AGGREGATOR_UNAVAILABLE"
    assert "РФ" in err.value.message


def test_send_requires_signer():
    svc = _service(FakeDex())
    with pytest.raises(SwapError) as err:
        svc._send_swap_sync(10**18, 50, "in_out", 0)
    assert err.value.code == "SIGNER_MISSING"


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth(client, username="swap"):
    client.post("/api/v1/auth/register", json={"username": username, "password": "swap-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "swap-pass-123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_requires_auth(client):
    assert client.get("/api/v1/swap/info").status_code == 401


def test_api_quote_flow(client, monkeypatch):
    headers = _auth(client)

    async def fake_quote(self, amount_in, slippage_bps=50, direction="in_out"):
        return {"amount_in": str(amount_in), "amount_out": "990099009900990099",
                "min_amount_out": "985148514851485148", "slippage_bps": slippage_bps,
                "price_impact_bps": 10, "router": "0xDEX",
                "source": "mockdex(uniswap-v2)", "aggregator_available": False}

    monkeypatch.setattr(SwapService, "quote", fake_quote)
    response = client.get("/api/v1/swap/quote?amount_in=1000000000000000000", headers=headers)
    assert response.status_code == 200
    assert response.json()["amount_out"] == "990099009900990099"


def test_api_execute_and_error_mapping(client, monkeypatch):
    headers = _auth(client, "swap_exec")

    async def fake_execute(self, amount_in, slippage_bps=50, direction="in_out", max_slippage_bps=0):
        return {"tx_hash": "0xswap", "status": 1, "block": 1, "gas_used": 1,
                "chain_id": 11155111, "amount_in": str(amount_in),
                "amount_out": "1", "min_amount_out": "1", "slippage_bps": slippage_bps,
                "price_impact_bps": 5}

    monkeypatch.setattr(SwapService, "execute", fake_execute)
    response = client.post("/api/v1/swap/execute", json={"amount_in": "100"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["tx_hash"] == "0xswap"

    async def forbidden(self, amount_in, slippage_bps=50, direction="in_out"):
        raise SwapError("MAINNET_FORBIDDEN", "нельзя")

    monkeypatch.setattr(SwapService, "quote", forbidden)
    response = client.get("/api/v1/swap/quote?amount_in=100", headers=headers)
    assert response.status_code == 403

    async def no_key(self, amount_in, slippage_bps=50, direction="in_out", max_slippage_bps=0):
        raise SwapError("SIGNER_MISSING", "нет ключа")

    monkeypatch.setattr(SwapService, "execute", no_key)
    response = client.post("/api/v1/swap/execute", json={"amount_in": "100"}, headers=headers)
    assert response.status_code == 503


def test_api_aggregator_honest_error(client):
    headers = _auth(client, "swap_agg")
    response = client.get("/api/v1/swap/aggregator", headers=headers)
    assert response.status_code == 503
    assert "AGGREGATOR_UNAVAILABLE" in response.json()["detail"]
