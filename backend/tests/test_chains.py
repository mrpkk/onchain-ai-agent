"""Тесты S5-07: реестр сетей, health-пробы с fallback и TTL-кэшем, API."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent import chains as chains_module  # noqa: E402
from src.agent.chains import CHAINS, ChainHealthCache, get_chain  # noqa: E402
from src.db import database  # noqa: E402


def test_registry_contents():
    assert set(CHAINS) == {"ethereum", "sepolia", "base", "base_sepolia", "bsc", "polygon"}
    assert CHAINS["ethereum"].chain_id == 1
    assert CHAINS["sepolia"].chain_id == 11155111
    assert CHAINS["base"].chain_id == 8453
    assert CHAINS["base_sepolia"].chain_id == 84532
    for cfg in CHAINS.values():
        assert cfg.rpcs and all(r.startswith("https://") for r in cfg.rpcs)
        assert cfg.explorer.startswith("https://")
        assert cfg.finality_blocks > 0


def test_get_chain_by_name_and_id():
    assert get_chain("base").chain_id == 8453
    assert get_chain(8453).name == "base"
    assert get_chain("unknown") is None


def test_perception_uses_registry():
    from src.agent.perception import BlockchainPerception

    legacy = BlockchainPerception(chains=[]).CHAIN_CONFIGS
    assert legacy["ethereum"]["chain_id"] == 1
    assert legacy["base"]["rpcs"][0].startswith("https://")
    assert "llamarpc" not in legacy["ethereum"]["rpc"]


def test_health_fallback_and_cache(monkeypatch):
    calls = []

    def fake_probe(rpc_url, timeout=5.0):
        calls.append(rpc_url)
        if "bad" in rpc_url:
            return None, "ConnectionError", 5
        return 123, None, 10

    monkeypatch.setattr(chains_module, "_probe_rpc", fake_probe)
    cache = ChainHealthCache(ttl_sec=60)

    # подменяем rpcs первой сети на [bad, good]
    from dataclasses import replace

    bad_good = replace(CHAINS["ethereum"], rpcs=("https://bad-rpc", "https://good-rpc"))
    monkeypatch.setitem(chains_module.CHAINS, "ethereum", bad_good)

    health = cache.probe("ethereum")
    assert health.status == "ok"
    assert health.rpc_used == "https://good-rpc"
    assert health.block_number == 123
    assert calls == ["https://bad-rpc", "https://good-rpc"]

    # второй вызов — из кэша, без новых проб
    assert cache.probe("ethereum").status == "ok"
    assert calls == ["https://bad-rpc", "https://good-rpc"]

    # force — повторная проба
    cache.probe("ethereum", force=True)
    assert len(calls) == 4


def test_health_down_when_all_fail(monkeypatch):
    monkeypatch.setattr(chains_module, "_probe_rpc", lambda url, timeout=5.0: (None, "Timeout", 5))
    cache = ChainHealthCache()
    health = cache.probe("base")
    assert health.status == "down"
    assert "Timeout" in (health.error or "")


@pytest.fixture
def client(monkeypatch):
    from src.api import main as main_module

    monkeypatch.setattr(chains_module, "_probe_rpc", lambda url, timeout=5.0: (777, None, 12))
    chains_module.shared_health().clear()
    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client
    chains_module.shared_health().clear()


def _auth(client, username="chains"):
    client.post("/api/v1/auth/register", json={"username": username, "password": "ch-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "ch-pass-123"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_chains_requires_auth(client):
    assert client.get("/api/v1/chains").status_code == 401


def test_api_chains_shape(client):
    headers = _auth(client)
    response = client.get("/api/v1/chains", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(CHAINS)
    by_name = {c["name"]: c for c in body["chains"]}
    assert by_name["base"]["chain_id"] == 8453
    assert by_name["base"]["health"]["status"] == "ok"
    assert by_name["ethereum"]["finality_blocks"] == 64
    assert by_name["ethereum"]["explorer"] == "https://etherscan.io"
