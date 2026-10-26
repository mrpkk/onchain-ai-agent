"""S2: бюджет конверта не превышается при параллельных запросах.

Главный тест слайса: 100 одновременных попыток при бюджете 50 × $0.05 →
ровно 50 ALLOW и 50 BLOCK, потрачено $2.50, ни цента сверху.
"""

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-ledger-")) / "ledger.db")
os.environ["KARTA_DEMO_EVENTS"] = str(Path(tempfile.mkdtemp(prefix="karta-events-")) / "e.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

from src.demo.app import create_app  # noqa: E402
from src.security.evidence import verify_payload  # noqa: E402

P = "/karta"
client = TestClient(create_app(P))
PAYEE = "api.example.com"


def _open(**kw) -> dict:
    body = {"budget_total": "2.50", "per_call_max": "0.05", "calls_max": 2000,
            "allowlist": [PAYEE], "ttl_hours": 2}
    body.update(kw)
    response = client.post(P + "/api/v1/envelopes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _spend(eid: str, amount: str = "0.05", **kw) -> dict:
    response = client.post(f"{P}/api/v1/envelopes/{eid}/spend",
                           json={"amount": amount, "payee": PAYEE, **kw})
    assert response.status_code == 200, response.text
    return response.json()


def test_concurrent_spending_never_exceeds_budget():
    eid = _open()["envelope_id"]
    with ThreadPoolExecutor(max_workers=32) as pool:
        verdicts = list(pool.map(lambda _: _spend(eid)["verdict"]["verdict"], range(100)))

    assert verdicts.count("ALLOW") == 50
    assert verdicts.count("BLOCK") == 50
    state = client.get(f"{P}/api/v1/envelopes/{eid}").json()
    assert state["spent"] == "2.50"
    assert state["remaining"] == "0.00"
    assert state["calls_used"] == 50


def test_receipt_is_issued_only_for_allowed_spends():
    eid = _open(budget_total="1", per_call_max="0.10")["envelope_id"]
    first = _spend(eid, "0.10")
    assert first["receipt"]["payload_sha256"]
    assert first["receipt"]["signed"] is True
    assert first["receipt"]["signature"] and first["receipt"]["public_key"]
    assert verify_payload(first["receipt"]) is True
    tampered = dict(first["receipt"]); tampered["amount"] = "999"
    assert verify_payload(tampered) is False
    blocked = _spend(eid, "5")
    assert blocked["verdict"]["verdict"] == "BLOCK"
    assert blocked["receipt"] is None


def test_unknown_payee_blocked_before_money_moves():
    eid = _open()["envelope_id"]
    response = client.post(f"{P}/api/v1/envelopes/{eid}/spend",
                           json={"amount": "0.05", "payee": "evil.example"})
    assert response.json()["verdict"]["rule"] == "E03"
    assert response.json()["envelope"]["spent"] == "0"


def test_invalid_envelope_is_400_with_contract_error():
    response = client.post(P + "/api/v1/envelopes", json={"budget_total": "abc"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_envelope"


def test_missing_envelope_is_404():
    assert client.get(P + "/api/v1/envelopes/env_missing").status_code == 404
