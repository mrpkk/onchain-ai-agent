"""S5: signed receipts and the public offline /verify page."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("DEBUG", "true")
os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-receipt-")) / "ledger.db")
os.environ["KARTA_DEMO_EVENTS"] = str(Path(tempfile.mkdtemp(prefix="karta-receipt-events-")) / "e.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

from src.demo.app import create_app  # noqa: E402
from src.security.evidence import verify_payload  # noqa: E402


def test_sample_receipt_is_signed_and_verifiable():
    with TestClient(create_app("")) as client:
        response = client.get("/api/v1/receipt/sample")
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["signed"] is True
        assert receipt["algorithm"] == "Ed25519"
        assert verify_payload(receipt) is True
        tampered = dict(receipt)
        tampered["amount"] = "999"
        assert verify_payload(tampered) is False


def test_verify_page_is_offline_js():
    with TestClient(create_app("")) as client:
        page = client.get("/verify")
        assert page.status_code == 200
        assert "crypto.subtle.verify" in page.text
        assert "Ed25519" in page.text
        assert "Verify a KARTA receipt" in page.text
