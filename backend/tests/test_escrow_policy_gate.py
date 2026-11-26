"""Первый рубеж: deny-политика не даёт отправить эскроу-транзакцию через API.

26.11.2026: гейт Дхармы был только внутри агента (`OnChainAgent._policy_gate`), а у эндпоинтов
`/api/v1/escrow` его не было — политика не мешала создать эскроу на запрещённый адрес.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

BAD = "0x" + "de" * 20
GOOD = "0x" + "11" * 20

#: Политика как в test_dharma: allow-список обязателен, иначе компилятор не пропустит действие.
def _policy(addresses):
    return {"version": 1,
            "limits": {"per_tx_eth": 1.0, "daily_eth": 2.0,
                       "velocity": {"window_min": 10, "max_tx": 3},
                       "gas_gwei_cap": 60, "slippage_bps_max": 50},
            "allow": {"actions": ["escrow_create", "transfer"], "chains": [1, 137, 8453, 11155111, 31337]},
            "deny": {"actions": [], "addresses": addresses}}


def test_policy_gate_denies_blocked_payee(monkeypatch):
    from src.api.main import _escrow_policy_gate

    monkeypatch.setenv("KARTA_ESCROW_POLICY_JSON", json.dumps(_policy([BAD])))
    with pytest.raises(Exception) as exc:
        _escrow_policy_gate("escrow_create", {"to": BAD, "address": BAD, "amount_wei": "1000"})
    assert getattr(exc.value, "status_code", None) == 403
    detail = exc.value.detail
    assert detail["code"] == "POLICY_DENY" and detail["action"] == "escrow_create"


def test_policy_gate_allows_good_payee(monkeypatch):
    from src.api.main import _escrow_policy_gate

    monkeypatch.setenv("KARTA_ESCROW_POLICY_JSON", json.dumps(_policy([BAD])))
    _escrow_policy_gate("escrow_create", {"to": GOOD, "address": GOOD, "amount_wei": "1000"})


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from src.api import main as main_module
    from src.db import database

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_denied_escrow_create_returns_403_before_chain(client, monkeypatch):
    """Эндпоинт обязан ответить 403 и не звать сеть — проверяем по ответу, не по моку сервиса."""
    client.post("/api/v1/auth/register", json={"username": "policy-gate", "password": "policy-pass-123"})
    token = client.post("/api/v1/auth/token",
                        json={"username": "policy-gate", "password": "policy-pass-123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    monkeypatch.setenv("KARTA_ESCROW_POLICY_JSON", json.dumps(_policy([BAD])))
    r = client.post("/api/v1/escrow", json={"payee": BAD, "amount_wei": "1000"}, headers=headers)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "POLICY_DENY"
