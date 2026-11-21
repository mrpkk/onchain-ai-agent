"""Возврат: runbook и правила совпадают с офертой; отказ и возврат проверены через API.

21.11.2026: правила возврата жили в `INVOICE-USDC.md`, а операционного порядка не было —
«вернём, если не доставим» держалось на памяти. Здесь два слоя:

* текст: runbook обязан повторять те же сроки и проценты, что оферта и страница оффера;
* код: возврат эскроу требует авторизации и отдаёт понятный HTTP-код при ошибке цепи.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.integrations.escrow import EscrowError, EscrowService  # noqa: E402


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_runbook_repeats_the_offer_rules():
    """Один срок и один процент во всех трёх местах — иначе клиент получит три правды."""
    runbook = _read("docs/REFUND-RUNBOOK.md")
    invoice = _read("docs/INVOICE-USDC.md")

    for text in (runbook, invoice):
        assert "5 рабочих дней" in text or "five business days" in text
    assert re.search(r"100\s?%", runbook) and re.search(r"100\s?%", invoice)
    assert "non-refundable" in invoice or "без возврата" in runbook


def test_runbook_has_the_operational_checklist():
    runbook = _read("docs/REFUND-RUNBOOK.md")
    for needle in ("tx_hash", "Basescan", "PROGRESS.md", "шаблон", "тот же адрес"):
        assert needle in runbook.lower() or needle in runbook, needle
    assert "progress.py" in runbook


def test_offer_page_links_the_same_rule():
    """Страница оффера не должна обещать другого срока."""
    page = _read("backend/src/demo/pages.py")
    assert "refund" in page.lower()
    assert "5 business days" in page or "5 рабочих дней" in page


@pytest.fixture()
def client():
    """Как в test_escrow: сброс движка БД и TestClient в контексте (иначе нет таблиц)."""
    from src.api import main as main_module
    from src.db import database

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _setup(client, name: str):
    client.post("/api/v1/auth/register", json={"username": name, "password": "refund-pass-123"})
    token = client.post("/api/v1/auth/token",
                        json={"username": name, "password": "refund-pass-123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, {"name": name, "tier": 1}


def test_refund_requires_authentication(client):
    assert client.post("/api/v1/escrow/0/refund").status_code == 401


def test_refund_reports_chain_errors_as_http(client, monkeypatch):
    headers, payload = _setup(client, "refund_err")
    client.post("/api/v1/agents", json=payload, headers=headers)

    async def not_found(self, escrow_id):
        raise EscrowError("NOT_FOUND", str(escrow_id))

    monkeypatch.setattr(EscrowService, "refund", not_found)
    assert client.post("/api/v1/escrow/999/refund", headers=headers).status_code == 404


def test_refund_success_returns_chain_evidence(client, monkeypatch):
    headers, payload = _setup(client, "refund_ok")
    client.post("/api/v1/agents", json=payload, headers=headers)

    async def ok(self, escrow_id):
        return {"tx_hash": "0xrefund", "status": 1, "block": 42,
                "gas_used": 21000, "chain_id": 8453}

    monkeypatch.setattr(EscrowService, "refund", ok)
    r = client.post("/api/v1/escrow/1/refund", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["tx_hash"] == "0xrefund" and body["chain_id"] == 8453
