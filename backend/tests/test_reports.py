"""Тесты S4-07: отчёты — честная сводка (газ/счётчики, PnL-pending) и CSV-экспорт."""
import asyncio
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import (  # noqa: E402
    AgentRepository,
    DecisionRepository,
    Transaction,
    UserRepository,
    database,
    session_scope,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client_env():
    from src.api import main as main_module

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    with TestClient(main_module.app) as client:
        yield client


def _auth(client, username="rep-user") -> str:
    client.post("/api/v1/auth/register",
                json={"username": username, "password": "pass12345"})
    return client.post("/api/v1/auth/token",
                       json={"username": username, "password": "pass12345"}).json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _agent(client, token) -> str:
    return client.post("/api/v1/agents", json={"name": "rep-agent"},
                       headers=_h(token)).json()["id"]


def _seed(client, agent_id: str, *, with_tx: bool = True):
    async def _seed_async():
        async with session_scope() as session:
            repo = DecisionRepository(session)
            await repo.add(uuid.UUID(agent_id), action="transfer",
                           params={"amount": 0.1}, reasoning="r1")
            await repo.add(uuid.UUID(agent_id), action="hold",
                           reasoning="r2")
            if with_tx:
                session.add(Transaction(
                    agent_id=uuid.UUID(agent_id), status="confirmed", chain_id=11155111,
                    action="transfer", tx_hash="0xtx1", gas_used=21000,
                    gas_price_gwei=20.0, simulated=False,
                ))
        return True

    database.reset_engine()
    _run(_seed_async())
    database.reset_engine()


def test_summary_counts_gas_and_honest_pnl(client_env):
    client = client_env
    token = _auth(client)
    agent_id = _agent(client, token)
    _seed(client, agent_id)

    response = client.get(f"/api/v1/agents/{agent_id}/reports/summary", headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["decisions_count"] == 2
    assert body["transactions_count"] == 1
    assert body["transactions_confirmed"] == 1
    assert body["gas_spent_eth"] == pytest.approx(21000 * 20.0 / 1e9, rel=1e-6)
    assert body["pnl_available"] is False
    assert body["realized_pnl"] is None
    assert "Phase 5" in body["pnl_reason"]


def test_decisions_csv_export(client_env):
    client = client_env
    token = _auth(client)
    agent_id = _agent(client, token)
    _seed(client, agent_id)

    response = client.get(f"/api/v1/agents/{agent_id}/export.csv?dataset=decisions",
                          headers=_h(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("id,created_at,action,risk_level")
    assert any("transfer" in line for line in lines[1:])


def test_transactions_csv_export_empty_ok(client_env):
    client = client_env
    token = _auth(client)
    agent_id = _agent(client, token)
    _seed(client, agent_id)

    response = client.get(f"/api/v1/agents/{agent_id}/export.csv?dataset=transactions",
                          headers=_h(token))
    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert len(lines) == 2  # header + 1 tx
    assert "0xtx1" in lines[1]


def test_audit_csv_export(client_env, monkeypatch):
    client = client_env
    monkeypatch.setenv("SAKSHI_AUDIT_KEY", "test-audit-key")
    token = _auth(client)
    agent_id = _agent(client, token)

    async def _seed_audit():
        from src.security.sakshi import SakshiLog
        async with session_scope() as session:
            await SakshiLog("test-audit-key").append(
                session, actor="agent", event_type="agent_started",
                payload={"name": "rep-agent"}, agent_id=uuid.UUID(agent_id),
            )

    database.reset_engine()
    _run(_seed_audit())
    database.reset_engine()

    response = client.get(f"/api/v1/agents/{agent_id}/export.csv?dataset=audit",
                          headers=_h(token))
    assert response.status_code == 200
    assert "agent_started" in response.text
    assert "prev_hash" in response.text.splitlines()[0]


def test_invalid_dataset_rejected(client_env):
    client = client_env
    token = _auth(client)
    agent_id = _agent(client, token)
    response = client.get(f"/api/v1/agents/{agent_id}/export.csv?dataset=hack",
                          headers=_h(token))
    assert response.status_code == 422


def test_reports_ownership_isolation(client_env):
    client = client_env
    token = _auth(client, "rep-owner")
    agent_id = _agent(client, token)
    other = _auth(client, "rep-other")

    assert client.get(f"/api/v1/agents/{agent_id}/reports/summary",
                      headers=_h(other)).status_code == 404
    assert client.get(f"/api/v1/agents/{agent_id}/export.csv",
                      headers=_h(other)).status_code == 404
