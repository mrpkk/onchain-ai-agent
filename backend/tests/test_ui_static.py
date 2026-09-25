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
    assert "/static/i18n.js" in body
    assert 'id="lang-btn"' in body
    assert "data-i18n=" in body


def test_static_assets_served(client):
    for path, needle in (
        ("/static/tokens.css", "--bg-primary"),
        ("/static/dashboard.css", ".decision-card"),
        ("/static/dashboard.css", '.badge[data-state="live"]'),
        ("/static/dashboard.js", "getElementById"),
        ("/static/dashboard.js", "new WebSocket"),
        ("/static/dashboard.js", "decision.proposed"),
        ("/static/dashboard.js", 't("btn.why")'),
        ("/static/dashboard.js", "parseChat"),
        ("/static/dashboard.js", "intent/confirm"),
        ("/static/dashboard.js", "startOnboarding"),
        ("/static/dashboard.js", "onbFinish"),
        ("/static/dashboard.js", "downloadCsv"),
        ("/static/dashboard.js", "refreshApprovals"),
        ("/static/dashboard.js", "approvalCard"),
        ("/static/dashboard.js", "parsePolicyRule"),
        ("/static/dashboard.js", "applyPolicyRule"),
        ("/static/dashboard.js", "simulatePolicyRule"),
        ("/static/dashboard.js", "/drift"),
        ("/static/dashboard.js", "btn.replay"),
        ("/static/dashboard.js", "refreshReport"),
        ("/static/dashboard.css", ".onb-card"),
        ("/static/manifest.webmanifest", "KARTA"),
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert needle in response.text, path


def test_manifest_is_valid_json(client):
    data = json.loads(client.get("/static/manifest.webmanifest").text)
    assert data["short_name"] == "KARTA"
    assert data["theme_color"] == "#0A0E17"


def test_manifest_declares_icons(client):
    """S4-09: PWA-манифест объявляет набор иконок логотипа."""
    data = json.loads(client.get("/static/manifest.webmanifest").text)
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"16x16", "32x32", "48x48", "180x180", "512x512"} <= sizes


def test_brand_assets_served(client):
    """S4-09: PNG-ассеты монограммы K отдаются и подключены в кокпите."""
    body = client.get("/").text
    assert "/static/icons/icon-32.png" in body
    assert "/static/icons/apple-touch-icon.png" in body
    assert "/static/icons/og-image.png" in body
    for icon in ("icon-16.png", "icon-32.png", "icon-48.png", "icon-180.png",
                 "icon-512.png", "apple-touch-icon.png", "og-image.png"):
        response = client.get(f"/static/icons/{icon}")
        assert response.status_code == 200, icon
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n", icon


def test_dashboard_ids_present(client):
    """Ключевые id разметки на месте (связность HTML↔JS после выноса)."""
    body = client.get("/").text
    for element_id in ("auth-screen", "dash-screen", "agent-list", "create-modal",
                       "goal-modal", "tx-panel", "toast", "chat-input",
                       "chat-preview", "chat-result", "onboarding-modal",
                       "onb-step-1", "onb-step-3", "report-summary",
                       "approvals-list", "approvals-count", "policy-input",
                       "policy-preview", "ric-wallet", "ric-parties", "ric-token", "ric-milestones", "ric-list",
                       "registry-panel", "registry-body", "escrow-wallet", "escrow-agent",
                       "escrow-amount", "escrow-list", "swap-info", "swap-amount", "swap-slippage",
                       "swap-quote", "bridge-info", "bridge-from", "bridge-to",
                       "bridge-amount", "bridge-quote", "aa-info", "aa-session-key",
                       "aa-limit", "aa-target", "aa-value", "aa-use-session", "aa-result"):
        assert f'id="{element_id}"' in body, element_id


def test_i18n_dictionary_parity():
    """RU/EN словари обязаны иметь одинаковый набор ключей (S4-08)."""
    import re

    source = (ROOT / "backend/src/api/static/i18n.js").read_text(encoding="utf-8")
    ru_block = source.split("  ru: {", 1)[1].split("  en: {", 1)[0]
    en_block = source.split("  en: {", 1)[1].split("\n  },\n};", 1)[0]

    def keys(block: str) -> set:
        return set(re.findall(r'"([\w.]+)":', block))

    ru_keys, en_keys = keys(ru_block), keys(en_block)
    assert ru_keys, "RU-словарь пуст"
    assert ru_keys == en_keys, f"Расхождение ключей: {ru_keys ^ en_keys}"
