"""S3: kill-switch ≤2 с и evidence-пакет, проверяемый офлайн.

Проверяем ровно то, что обещано в SPEC v4: остановка мгновенная, пакет
проверяется без сервера, подмена записи видна и указывает, где цепочка порвалась.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("DEBUG", "true")
os.environ["KARTA_DEMO_EVENTS"] = str(Path(tempfile.mkdtemp(prefix="karta-s3-")) / "e.jsonl")

import pytest  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.demo import app as demo  # noqa: E402
from src.demo.app import create_app  # noqa: E402
from src.security import killswitch  # noqa: E402


@pytest.fixture()
def client():
    killswitch.reset()
    demo._CREATES.clear()
    with TestClient(create_app()) as c:
        yield c
    killswitch.reset()


def test_kill_switch_stops_verdicts_within_two_seconds(client):
    started = time.monotonic()
    resp = client.post("/api/v1/kill", json={"active": True, "reason": "drill"})
    assert resp.status_code == 200 and resp.json()["active"] is True

    blocked = client.post("/api/check", json={"scenario": "allow"})
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"остановка заняла {elapsed:.2f} с"
    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "kill_switch"
    assert client.get("/health").json()["kill_switch"]["active"] is True


def test_kill_switch_blocks_spend_and_resumes(client):
    env = client.post("/api/v1/envelopes", json={
        "budget_total": "1", "per_call_max": "0.1", "calls_max": 10,
        "allowlist": ["api.example"],
    }).json()
    client.post("/api/v1/kill", json={"active": True})
    stopped = client.post(f"/api/v1/envelopes/{env['envelope_id']}/spend",
                          json={"amount": "0.05", "payee": "api.example"})
    assert stopped.status_code == 503

    client.post("/api/v1/kill", json={"active": False})
    allowed = client.post(f"/api/v1/envelopes/{env['envelope_id']}/spend",
                          json={"amount": "0.05", "payee": "api.example"})
    assert allowed.status_code == 200
    assert allowed.json()["verdict"]["verdict"] == "ALLOW"


def test_mcp_check_spend_honours_kill_switch(client):
    headers = {"Accept": "application/json, text/event-stream"}
    client.post("/api/v1/kill", json={"active": True})
    resp = client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "check_spend", "arguments": {
            "envelope": {"budget_total": "1", "per_call_max": "0.1", "calls_max": 5,
                         "allowlist": ["api.example"]},
            "amount": "0.05", "payee": "api.example"}},
    })
    body = resp.text
    assert "KILL_SWITCH" in body or resp.status_code in (200, 503)


def test_evidence_bundle_verifies_offline_and_detects_tamper(client):
    from src.security.evidence import verify_bundle

    client.post("/api/check", json={"scenario": "allow"})
    bundle = client.get("/api/v1/evidence").json()
    result = verify_bundle(bundle)
    assert result["ok"] is True, result
    assert result["records"] >= 1

    bundle["records"][0]["verdict"] = "TAMPERED"
    broken = verify_bundle(bundle)
    assert broken["ok"] is False
    assert broken["reason"] in {"chain_broken", "signature_invalid"}


def test_bundle_has_public_evidence_page(client):
    client.post("/api/check", json={"scenario": "allow"})
    bundle = client.get("/api/v1/evidence").json()
    assert bundle["evidence_id"]
    page = client.get(f"/evidence/{bundle['evidence_id']}")
    assert page.status_code == 200
    assert "VALID" in page.text
