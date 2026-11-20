"""S9: public USDC invoice page and transaction check."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("DEBUG", "true")
os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-inv-ledger-")) / "ledger.db")
os.environ["KARTA_INVOICES_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-inv-")) / "invoices.db")

from fastapi.testclient import TestClient  # noqa: E402

from src.billing import usdc_invoice  # noqa: E402
from src.demo.app import create_app  # noqa: E402


def _invoice() -> dict:
    return usdc_invoice.create("2500", "KARTA pilot", address="0x" + "a" * 40)


def test_invoice_page_shows_amount_and_address():
    item = _invoice()
    with TestClient(create_app("")) as client:
        page = client.get(f"/invoice/{item['id']}")
        assert page.status_code == 200
        assert "2500" in page.text and item["address"] in page.text
        assert "pending" in page.text


def test_unknown_invoice_is_404():
    with TestClient(create_app("")) as client:
        assert client.get("/invoice/inv_doesnotexist").status_code == 404


def test_unconfirmed_tx_stays_pending(monkeypatch):
    item = _invoice()
    monkeypatch.setattr(usdc_invoice, "onchain_paid", lambda tx, address: None)
    with TestClient(create_app("")) as client:
        response = client.post(f"/api/v1/invoice/{item['id']}/check",
                               json={"tx_hash": "0x" + "b" * 64})
        assert response.status_code == 200
        assert response.json()["status"] == "pending"


def test_confirmed_tx_marks_paid(monkeypatch):
    item = _invoice()
    monkeypatch.setattr(usdc_invoice, "onchain_paid", lambda tx, address: usdc_invoice.Decimal("2500"))
    with TestClient(create_app("")) as client:
        response = client.post(f"/api/v1/invoice/{item['id']}/check",
                               json={"tx_hash": "0x" + "c" * 64})
        assert response.status_code == 200
        assert response.json()["status"] == "paid"
        assert response.json()["tx_hash"] == "0x" + "c" * 64
