"""KARTA public pricing/enterprise pages: one price, no fake certifications."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("DEBUG", "true")
os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-pages-")) / "ledger.db")

from fastapi.testclient import TestClient  # noqa: E402

from src.demo.app import create_app  # noqa: E402


def test_pricing_has_five_tiers_and_no_card_claim():
    with TestClient(create_app("")) as client:
        page = client.get("/pricing")
        assert page.status_code == 200
        for needle in ("Open", "Team", "Pilot", "Enterprise", "Retainer", "$2,500", "$25,000"):
            assert needle in page.text
        assert "no card checkout is claimed" in page.text


def test_enterprise_page_answers_twelve_questions():
    with TestClient(create_app("")) as client:
        page = client.get("/enterprise")
        assert page.status_code == 200
        for n in range(1, 13):
            assert f"<td>{n}</td>" in page.text
        assert "LEGAL REVIEW REQUIRED" in page.text
        assert "100% safe" not in page.text
