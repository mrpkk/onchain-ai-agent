"""Тесты S6-04: MCP-сервер KARTA (read-only, streamable HTTP, скоуп владельца ключа)."""

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
from src.mcp.contracts import READ_TOOLS, WRITE_TOOLS_GATED  # noqa: E402

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _setup(client, username="mcpuser", scopes=None):
    client.post("/api/v1/auth/register", json={"username": username, "password": "mcp-pass-123"})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": "mcp-pass-123"}
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    key = client.post(
        "/api/v1/api-keys",
        json={"name": "test", "scopes": scopes or ["mcp:read"]},
        headers=auth,
    ).json()["key"]
    agent = client.post("/api/v1/agents", json={"name": "mcp-agent", "tier": 1}, headers=auth).json()
    return {"auth": auth, "key": key, "agent": agent}


def _rpc(client, method, params=None, key=None, request_id=1):
    headers = dict(MCP_HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        headers=headers,
    )


def _tool_text(response) -> str:
    return response.json()["result"]["content"][0]["text"]


def test_mcp_initialize_and_tools_list(client):
    env = _setup(client)

    init = _rpc(client, "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "test", "version": "1"}})
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "karta"

    listing = _rpc(client, "tools/list", key=env["key"])
    assert listing.status_code == 200
    names = {t["name"] for t in listing.json()["result"]["tools"]}
    assert names == set(READ_TOOLS)


def test_write_tools_not_registered(client):
    """OWASP MCP: excessive agency — write-tools gated и НЕ зарегистрированы в v1."""
    env = _setup(client, username="mcpguard")
    listing = _rpc(client, "tools/list", key=env["key"])
    names = {t["name"] for t in listing.json()["result"]["tools"]}
    assert names.isdisjoint(set(WRITE_TOOLS_GATED))


def test_contracts_parity_with_docs():
    """Pinned definitions: контракты и doc-файл не расходятся."""
    doc_path = ROOT / "docs" / "MCP_TOOL_CONTRACTS.md"
    if not doc_path.exists():
        pytest.skip("MCP_TOOL_CONTRACTS.md ещё не сгенерирован")
    doc = doc_path.read_text(encoding="utf-8")
    for name in READ_TOOLS:
        assert f"`{name}`" in doc, name
    for name in WRITE_TOOLS_GATED:
        assert f"`{name}`" in doc, name


def test_tool_call_returns_owner_scoped_data(client):
    env = _setup(client)

    call = _rpc(client, "tools/call",
                {"name": "get_wallet", "arguments": {"agent_id": env["agent"]["id"]}},
                key=env["key"])
    assert call.status_code == 200
    text = _tool_text(call)
    assert env["agent"]["id"] in text
    assert "mcp-agent" in text


def test_tool_call_unauthorized_without_key(client):
    env = _setup(client, username="mcpnoauth")

    call = _rpc(client, "tools/call",
                {"name": "get_wallet", "arguments": {"agent_id": env["agent"]["id"]}})
    assert "UNAUTHORIZED" in _tool_text(call)


def test_tool_call_foreign_agent_not_found(client):
    env_a = _setup(client, username="mcpa")
    env_b = _setup(client, username="mcpb")

    call = _rpc(client, "tools/call",
                {"name": "get_wallet", "arguments": {"agent_id": env_a["agent"]["id"]}},
                key=env_b["key"])
    assert "NOT_FOUND" in _tool_text(call)


def test_revoked_key_rejected(client):
    env = _setup(client, username="mcp_revoke")

    keys = client.get("/api/v1/api-keys", headers=env["auth"]).json()
    client.delete(f"/api/v1/api-keys/{keys[0]['id']}", headers=env["auth"])

    call = _rpc(client, "tools/call",
                {"name": "get_wallet", "arguments": {"agent_id": env["agent"]["id"]}},
                key=env["key"])
    assert "UNAUTHORIZED" in _tool_text(call)


def test_mcp_remaining_read_tools(client, monkeypatch):
    """Покрытие read-tools: transactions/portfolio/audit/decision + RPC-пути (balance/gas)."""
    env = _setup(client, username="mcp_tools")

    async def fake_rpc(rpc_url, fn):
        class FakeW3:
            class eth:
                chain_id = 11155111
                block_number = 100
                gas_price = 25 * 10**9

                @staticmethod
                def get_balance(_addr):
                    return 123456789

                @staticmethod
                def get_block(_):
                    class B:
                        baseFeePerGas = 20 * 10**9
                        number = 100
                    return B()

            @staticmethod
            def to_checksum_address(a):
                return a

        return fn(FakeW3()), None

    monkeypatch.setattr("src.mcp.server._rpc_call", fake_rpc)

    for tool in ("get_balance", "get_gas", "get_portfolio"):
        call = _rpc(client, "tools/call",
                    {"name": tool, "arguments": {"agent_id": env["agent"]["id"]}},
                    key=env["key"])
        assert call.status_code == 200, tool
        assert "error" not in _tool_text(call) or "NO_WALLET" in _tool_text(call)

    call = _rpc(client, "tools/call",
                {"name": "get_transactions", "arguments": {"agent_id": env["agent"]["id"]}},
                key=env["key"])
    assert '"total"' in _tool_text(call)

    monkeypatch.setenv("SAKSHI_AUDIT_KEY", "test-audit-key")
    call = _rpc(client, "tools/call",
                {"name": "audit_log", "arguments": {"agent_id": env["agent"]["id"]}},
                key=env["key"])
    assert "items" in _tool_text(call)

    call = _rpc(client, "tools/call",
                {"name": "get_decision", "arguments": {"decision_id": "not-a-uuid"}},
                key=env["key"])
    assert "NOT_FOUND" in _tool_text(call)
