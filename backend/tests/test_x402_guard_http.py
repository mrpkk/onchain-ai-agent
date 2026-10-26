"""S4: HTTP boundary for the x402 guard (no network, no payment)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("DEBUG", "true")
os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-x402-http-")) / "ledger.db")

from fastapi.testclient import TestClient  # noqa: E402

from src.demo.app import create_app  # noqa: E402
from src.security import killswitch  # noqa: E402

CHALLENGE = {"accepts": [{
    "scheme": "exact", "network": "eip155:8453", "asset": "USDC",
    "amount": "10000", "payTo": "0xabc",
    "resource": "https://api.example.com/search", "decimals": 6,
}]}


def _client() -> TestClient:
    killswitch.reset()
    return TestClient(create_app(""))


def _envelope(client, budget="0.02") -> str:
    response = client.post("/api/v1/envelopes", json={
        "budget_total": budget, "per_call_max": "0.01", "calls_max": 100,
        "allowlist": ["api.example.com"],
    })
    assert response.status_code in (200, 201), response.text
    return response.json()["envelope_id"]


def test_runaway_loop_stops_at_the_http_boundary():
    with _client() as client:
        envelope_id = _envelope(client, "0.02")
        verdicts = []
        for _ in range(5):
            response = client.post("/api/v1/x402/check", json={
                "envelope_id": envelope_id, "challenge": CHALLENGE,
            })
            assert response.status_code == 200, response.text
            verdicts.append(response.json()["verdict"]["rule"])
        assert verdicts[:2] == ["E00", "E00"]
        assert verdicts[2] == "E06"
        state = client.get(f"/api/v1/envelopes/{envelope_id}").json()
        assert state["spent"] == "0.02"
        assert state["remaining"] == "0.00"


def test_unknown_vendor_is_refused_before_charging():
    with _client() as client:
        envelope_id = _envelope(client)
        bad = {"accepts": [{**CHALLENGE["accepts"][0],
                            "resource": "https://evil.example/x"}]}
        response = client.post("/api/v1/x402/check", json={
            "envelope_id": envelope_id, "challenge": bad,
        })
        assert response.status_code == 200
        assert response.json()["verdict"]["rule"] == "E03"
        assert client.get(f"/api/v1/envelopes/{envelope_id}").json()["spent"] == "0"


def test_invalid_challenge_is_400_not_a_charge():
    with _client() as client:
        envelope_id = _envelope(client)
        response = client.post("/api/v1/x402/check", json={
            "envelope_id": envelope_id, "challenge": {"amount": "abc"},
        })
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_challenge"


def test_kill_switch_blocks_x402_guard():
    with _client() as client:
        envelope_id = _envelope(client)
        client.post("/api/v1/kill", json={"active": True, "reason": "drill"})
        response = client.post("/api/v1/x402/check", json={
            "envelope_id": envelope_id, "challenge": CHALLENGE,
        })
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "kill_switch"
