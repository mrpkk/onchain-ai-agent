"""Тесты S4-17: реконсиляция статусов при старте (честные состояния после падения процесса)."""

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.api.models import AgentStatus  # noqa: E402
from src.db import AgentRepository, UserRepository, database, session_scope  # noqa: E402
from src.runtime.reconciliation import reconcile_on_startup, reconcile_stale_agents  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh_db():
    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    yield


def _seed_running_and_finished():
    async def _flow():
        async with session_scope() as session:
            user = await UserRepository(session).create("rec", "h")
            repo = AgentRepository(session)
            running = await repo.create(user.id, name="r1", status=AgentStatus.RUNNING.value)
            stopped = await repo.create(user.id, name="s1", status=AgentStatus.STOPPED.value)
            killed = await repo.create(user.id, name="k1", status=AgentStatus.KILLED.value)
            created = await repo.create(user.id, name="c1", status=AgentStatus.CREATED.value)
            return str(running.id), str(stopped.id), str(killed.id), str(created.id)

    return _run(_flow())


def _status(agent_id: str) -> str:
    async def _read():
        async with session_scope() as session:
            agent = await AgentRepository(session).get(uuid.UUID(agent_id))
            assert agent is not None
            return agent.status

    return _run(_read())


def test_running_agents_reconciled_stopped_others_untouched():
    running_id, stopped_id, killed_id, created_id = _seed_running_and_finished()

    fixed = _run(reconcile_on_startup())

    assert fixed == 1
    assert _status(running_id) == AgentStatus.STOPPED.value
    assert _status(stopped_id) == AgentStatus.STOPPED.value
    assert _status(killed_id) == AgentStatus.KILLED.value
    assert _status(created_id) == AgentStatus.CREATED.value


def test_reconcile_idempotent():
    _seed_running_and_finished()

    assert _run(reconcile_on_startup()) == 1
    assert _run(reconcile_on_startup()) == 0


def test_lifespan_reconciles_on_startup():
    from fastapi.testclient import TestClient

    from src.api import main as main_module

    running_id, *_ = _seed_running_and_finished()

    with TestClient(main_module.app):
        pass

    assert _status(running_id) == AgentStatus.STOPPED.value
