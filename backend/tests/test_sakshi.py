"""Тесты S2-02: Sakshi Log (HMAC-цепочка, экспорт) + decision diary + PG-триггер."""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402
from src.db import AgentRepository, DecisionRepository, UserRepository, database, session_scope  # noqa: E402
from src.security.sakshi import AuditKeyMissing, SakshiLog, compute_hash  # noqa: E402

AUDIT_KEY = "test-audit-key"
PG_URL = os.environ.get("KARTA_TEST_PG_URL", "postgresql+asyncpg://agent:agent@127.0.0.1:5433/onchain_ai")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    monkeypatch.setenv("SAKSHI_AUDIT_KEY", AUDIT_KEY)
    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    yield


async def _make_agent_row():
    async with session_scope() as session:
        user = await UserRepository(session).create("diary-user", "h")
        agent = await AgentRepository(session).create(user.id, name="diary-agent")
        return agent.id


def test_compute_hash_deterministic():
    payload = {"b": 2, "a": 1}
    first = compute_hash(AUDIT_KEY, "", payload)
    second = compute_hash(AUDIT_KEY, "", {"a": 1, "b": 2})  # порядок ключей не важен
    assert first == second
    assert first != compute_hash(AUDIT_KEY, "", {"a": 1, "b": 3})


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("SAKSHI_AUDIT_KEY", raising=False)
    monkeypatch.delenv("ONCHAIN_MASTER_KEY", raising=False)
    with pytest.raises(AuditKeyMissing):
        SakshiLog()


def test_chain_append_and_verify():
    agent_id = _run(_make_agent_row())
    log = SakshiLog(AUDIT_KEY)

    async def _flow():
        async with session_scope() as session:
            first = await log.append(session, actor="agent", event_type="decision_made",
                                     payload={"action": "hold"}, agent_id=agent_id)
            second = await log.append(session, actor="policy", event_type="policy_verdict",
                                      payload={"decision": "allow"}, agent_id=agent_id)
            third = await log.append(session, actor="agent", event_type="tx_submitted",
                                     payload={"tx": "0x1"}, agent_id=agent_id)
        async with session_scope() as session:
            events = await log.list_events(session, agent_id=agent_id)
        assert len(events) == 3
        assert first.prev_hash is None
        assert second.prev_hash == first.hash
        assert third.prev_hash == second.hash
        assert log.verify_chain(events) is True
        return events

    events = _run(_flow())
    assert log.verify_chain(events) is True


def test_tamper_breaks_chain():
    agent_id = _run(_make_agent_row())
    log = SakshiLog(AUDIT_KEY)

    async def _flow():
        async with session_scope() as session:
            await log.append(session, actor="agent", event_type="a", payload={"v": 1}, agent_id=agent_id)
            await log.append(session, actor="agent", event_type="b", payload={"v": 2}, agent_id=agent_id)
        async with session_scope() as session:
            events = await log.list_events(session, agent_id=agent_id)
        # подмена payload (эмуляция атаки; на SQLite триггера нет)
        events[1].payload = {"v": 999}
        return log.verify_chain(events)

    assert _run(_flow()) is False


def test_export_json_and_csv():
    agent_id = _run(_make_agent_row())
    log = SakshiLog(AUDIT_KEY)

    async def _flow():
        async with session_scope() as session:
            await log.append(session, actor="system", event_type="kill_switch",
                             payload={"mode": "hard"}, agent_id=agent_id)
        async with session_scope() as session:
            return await log.list_events(session, agent_id=agent_id)

    events = _run(_flow())
    as_json = log.export_json(events)
    as_csv = log.export_csv(events)
    assert '"event_type": "kill_switch"' in as_json
    assert "kill_switch" in as_csv
    assert "prev_hash" in as_csv.splitlines()[0]


def test_decision_diary_persists_decision():
    agent_id = _run(_make_agent_row())
    agent = OnChainAgent(AgentConfig(name="diary", chain="sepolia"),
                         db_agent_id=agent_id, sakshi=SakshiLog(AUDIT_KEY))
    decision = AgentDecision(action="transfer", params={"to": "0xabc", "amount": 0.1},
                             reasoning="тест", confidence=0.77, risk_level="medium")

    async def _flow():
        await agent._persist_decision(decision)
        await agent._sakshi_append("decision_made", {"action": "transfer", "confidence": 0.77})
        async with session_scope() as session:
            rows = await DecisionRepository(session).list_for_agent(agent_id)
            events = await SakshiLog(AUDIT_KEY).list_events(session, agent_id=agent_id)
        return rows, events

    rows, events = _run(_flow())
    assert len(rows) == 1
    assert rows[0].action == "transfer"
    assert rows[0].confidence == pytest.approx(0.77)
    assert rows[0].reasoning == "тест"
    assert len(events) == 1 and events[0].event_type == "decision_made"


def test_pg_append_only_trigger():
    """На PG: UPDATE audit_events заблокирован триггером (S2-02)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _check():
        engine = create_async_engine(PG_URL)
        try:
            import sqlalchemy as sa
            async with engine.begin() as conn:
                trigger = (await conn.execute(sa.text(
                    "select tgname from pg_trigger where tgname='trg_audit_events_append_only'"
                ))).scalar_one_or_none()
                if trigger is None:
                    return "no-trigger"
                await conn.execute(sa.text(
                    "insert into audit_events (actor, event_type, payload, prev_hash, hash, created_at) "
                    "values ('test', 'trigger_probe', '{}'::jsonb, null, 'x', now())"
                ))
                try:
                    await conn.execute(sa.text(
                        "update audit_events set actor='hacked' where event_type='trigger_probe'"
                    ))
                    return "allowed"
                except Exception:
                    return "blocked"
        finally:
            await engine.dispose()

    try:
        result = _run(_check())
    except Exception as e:  # PG недоступен (например, CI) — тест мягко пропускается
        pytest.skip(f"PG недоступен: {type(e).__name__}")
    if result == "no-trigger":
        pytest.skip("миграция 0002 не применена")
    assert result == "blocked"
