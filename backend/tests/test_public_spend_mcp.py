"""S2b: public stateless `check_spend` MCP tool.

No API key, no DB writes, no wallet. The same evaluator as demo/API.
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.demo.app import create_app  # noqa: E402

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _rpc(client, method, params=None, request_id=1):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        headers=MCP_HEADERS,
    )


def _call(client, arguments):
    response = _rpc(
        client,
        "tools/call",
        {"name": "check_spend", "arguments": arguments},
    )
    assert response.status_code == 200, response.text
    return json.loads(response.json()["result"]["content"][0]["text"])


def _envelope(**overrides):
    value = {
        "budget_total": "2500",
        "per_call_max": "0.05",
        "calls_max": 2000,
        "allowlist": ["api.marketdata.example"],
        "allow_new_payee": False,
        "allow_subscriptions": False,
        "expires_at": None,
    }
    value.update(overrides)
    return value


def test_initialize_and_tools_list_without_auth():
    with TestClient(create_app("")) as client:
        init = _rpc(client, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "karta-spend"

        listing = _rpc(client, "tools/list")
        assert listing.status_code == 200, listing.text
        names = {tool["name"] for tool in listing.json()["result"]["tools"]}
        assert "check_spend" in names


def test_runaway_calls_blocked_without_spending_budget():
    with TestClient(create_app("")) as client:
        result = _call(client, {
            "envelope": _envelope(),
            "amount": "0.05",
            "payee": "api.marketdata.example",
            "calls_so_far": 41000,
            "spent_so_far": "2050",
        })
        assert result["verdict"] == "BLOCK"
        assert result["rule"] == "E05"
        assert result["stateless"] is True


def test_new_payee_blocked():
    with TestClient(create_app("")) as client:
        result = _call(client, {
            "envelope": _envelope(),
            "amount": "940",
            "payee": "reports-vendor.xyz",
            "calls_so_far": 12,
            "spent_so_far": "3.20",
        })
        assert result["verdict"] == "BLOCK"
        assert result["rule"] == "E03"


def test_within_envelope_allowed():
    with TestClient(create_app("")) as client:
        result = _call(client, {
            "envelope": _envelope(),
            "amount": "0.04",
            "payee": "api.marketdata.example",
            "calls_so_far": 15,
            "spent_so_far": "0.75",
        })
        assert result["verdict"] == "ALLOW"
        assert result["rule"] == "E00"


def test_subscription_blocked():
    with TestClient(create_app("")) as client:
        result = _call(client, {
            "envelope": _envelope(),
            "amount": "9",
            "payee": "api.marketdata.example",
            "calls_so_far": 4,
            "spent_so_far": "0.20",
            "is_subscription": True,
        })
        assert result["verdict"] == "BLOCK"
        assert result["rule"] == "E02"
