"""Админ-контур: счёт выставляет только владелец, заявки читает только он.

Без этого «первые деньги» упираются в ручную возню: счёт должен создаваться одной
командой, а заявки — читаться там же, где живёт API.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="karta-admin-"))
os.environ["KARTA_INVOICES_DB"] = str(_TMP / "inv.db")
os.environ["KARTA_PILOTS"] = str(_TMP / "pilots.jsonl")
os.environ["KARTA_DEMO_EVENTS"] = str(_TMP / "events.jsonl")
os.environ["KARTA_USDC_ADDRESS"] = "0x1111111111111111111111111111111111111111"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from src.demo.app import create_app  # noqa: E402

P = "/karta"
TOKEN = "test-admin-token"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("KARTA_ADMIN_TOKEN", TOKEN)
    return TestClient(create_app(P))


def test_invoice_requires_token(client):
    assert client.post(P + "/api/v1/invoice", json={"amount": "2500"}).status_code == 403
    bad = client.post(P + "/api/v1/invoice", json={"amount": "2500"},
                      headers={"x-admin-token": "wrong"})
    assert bad.status_code == 403


def test_invoice_created_with_token(client):
    response = client.post(P + "/api/v1/invoice",
                           json={"amount": "2500", "memo": "KARTA pilot", "ttl_hours": 72},
                           headers={"x-admin-token": TOKEN})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["amount"] == "2500"
    assert item["status"] == "pending"
    assert item["address"] == "0x1111111111111111111111111111111111111111"


def test_invoice_disabled_without_env(client, monkeypatch):
    monkeypatch.delenv("KARTA_ADMIN_TOKEN", raising=False)
    response = client.post(P + "/api/v1/invoice", json={"amount": "10"},
                           headers={"x-admin-token": TOKEN})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_disabled"


def test_pilot_requests_are_owner_only(client):
    created = client.post(P + "/api/v1/pilot-requests",
                          json={"email": "buyer@example.com", "platform": "agent wallet"})
    assert created.status_code in (200, 201)

    assert client.get(P + "/api/v1/pilot-requests").status_code == 403
    listed = client.get(P + "/api/v1/pilot-requests", headers={"x-admin-token": TOKEN})
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] >= 1
    assert "ip" not in {k.lower() for k in body["items"][0]}
