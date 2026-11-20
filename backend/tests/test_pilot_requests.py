"""S7a: страница пилота и приём заявок.

Проверяем контракт, а не вёрстку: заявка сохраняется, мусорный email отклоняется,
сырой IP не пишется, лимит срабатывает.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEBUG", "true")
_TMP = Path(tempfile.mkdtemp(prefix="karta-s7-"))
os.environ["KARTA_DEMO_EVENTS"] = str(_TMP / "events.jsonl")
os.environ["KARTA_PILOTS"] = str(_TMP / "pilots.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.demo import app as demo  # noqa: E402
from src.security import killswitch  # noqa: E402


def _client():
    killswitch.reset()
    demo._CREATES.clear()
    return TestClient(demo.create_app())


def test_partners_page_renders():
    with _client() as client:
        page = client.get("/partners")
        assert page.status_code == 200
        assert "design partner" in page.text.lower()
        assert "/api/v1/pilot-requests" in page.text


def test_valid_request_is_stored_without_raw_ip():
    Path(os.environ["KARTA_PILOTS"]).unlink(missing_ok=True)
    with _client() as client:
        resp = client.post("/api/v1/pilot-requests", json={
            "email": "ada@example.com",
            "name": "Ada",
            "platform": "prices API agent",
            "scenario": "ran 40k calls",
        })
    assert resp.status_code == 201 and resp.json()["status"] == "received"

    lines = Path(os.environ["KARTA_PILOTS"]).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["email"] == "ada@example.com"
    assert record["scenario"] == "ran 40k calls"
    assert "ip_hash" in record and "testclient" not in record["ip_hash"]


def test_invalid_email_is_rejected():
    with _client() as client:
        resp = client.post("/api/v1/pilot-requests", json={"email": "not-an-email"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_email"


def test_rate_limit_applies():
    with _client() as client:
        for i in range(demo._CREATE_LIMIT):
            client.post("/api/v1/pilot-requests", json={"email": f"a{i}@example.com"})
        blocked = client.post("/api/v1/pilot-requests", json={"email": "late@example.com"})
    assert blocked.status_code == 429
