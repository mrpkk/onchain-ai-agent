"""Тесты S2-01: персистентность («рестарт»), репозитории, API-флоу на БД."""
import asyncio
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import AgentRepository, UserRepository, database, session_scope  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh_db():
    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    yield


async def _seed():
    async with session_scope() as session:
        user = await UserRepository(session).create("alice", "hash1")
        agent = await AgentRepository(session).create(user.id, name="persist-bot")
        return str(user.id), str(agent.id)


def test_data_survives_engine_reset():
    user_id, agent_id = _run(_seed())

    database.reset_engine()  # имитация рестарта: новый engine и соединения

    async def _read():
        async with session_scope() as session:
            user = await UserRepository(session).get_by_username("alice")
            agent = await AgentRepository(session).get(uuid.UUID(agent_id))
            return user, agent

    user, agent = _run(_read())
    assert user is not None and str(user.id) == user_id
    assert agent is not None
    assert agent.name == "persist-bot"
    assert str(agent.owner_id) == user_id


def test_agent_repository_crud():
    async def _flow():
        async with session_scope() as session:
            user = await UserRepository(session).create("bob", "h")
            repo = AgentRepository(session)
            first = await repo.create(user.id, name="a1")
            await repo.create(user.id, name="a2")
            listed = await repo.list_by_owner(user.id)
            assert [x.name for x in listed] == ["a2", "a1"]
            assert await repo.count_by_owner(user.id) == 2
            await repo.set_status(first, "running")
            assert await repo.count_running() == 1
            await repo.set_goal(first, "watch gas", "ctx")
            assert first.goal_text == "watch gas"
            return True

    assert _run(_flow())


def test_api_flow_persists_across_restart():
    from fastapi.testclient import TestClient
    from src.api import main as main_module

    with TestClient(main_module.app) as client:
        assert client.post("/api/v1/auth/register",
                           json={"username": "carol", "password": "pass12345"}).status_code == 201
        login = client.post("/api/v1/auth/token",
                            json={"username": "carol", "password": "pass12345"})
        assert login.status_code == 200
        token = login.json()["access_token"]

        created = client.post("/api/v1/agents",
                              json={"name": "persist-agent", "chain_id": 11155111},
                              headers={"Authorization": f"Bearer {token}"})
        assert created.status_code == 201

    database.reset_engine()  # «рестарт» процесса API

    with TestClient(main_module.app) as client2:
        login2 = client2.post("/api/v1/auth/token",
                              json={"username": "carol", "password": "pass12345"})
        assert login2.status_code == 200
        listing = client2.get("/api/v1/agents",
                              headers={"Authorization": f"Bearer {login2.json()['access_token']}"})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["agents"][0]["name"] == "persist-agent"
