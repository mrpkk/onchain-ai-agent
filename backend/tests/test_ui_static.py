"""Тесты S4-01: статический UI (server-rendered, без npm) и дизайн-токены."""
import json
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


@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def test_root_serves_cockpit(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "KARTA" in body
    assert "/static/tokens.css" in body and "/static/dashboard.js" in body
    assert "/static/manifest.webmanifest" in body


def test_static_assets_served(client):
    for path, needle in (
        ("/static/tokens.css", "--bg-primary"),
        ("/static/dashboard.css", ".agent-row"),
        ("/static/dashboard.js", "getElementById"),
        ("/static/manifest.webmanifest", "KARTA"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert needle in response.text, path


def test_manifest_is_valid_json(client):
    data = json.loads(client.get("/static/manifest.webmanifest").text)
    assert data["short_name"] == "KARTA"
    assert data["theme_color"] == "#0A0E17"


def test_dashboard_ids_present(client):
    """Ключевые id разметки на месте (связность HTML↔JS после выноса)."""
    body = client.get("/").text
    for element_id in ("auth-screen", "dash-screen", "agent-list", "create-modal",
                       "goal-modal", "tx-panel", "toast"):
        assert f'id="{element_id}"' in body, element_id
