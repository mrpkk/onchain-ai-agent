"""Тесты S4-06: Telegram-модуль + approvals (единый путь web/TG, policy не обходится)."""
import asyncio
import json
import os
import sys
import uuid
from contextlib import suppress
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402
from src.db import (  # noqa: E402
    AgentRepository,
    ApprovalRepository,
    DecisionRepository,
    UserRepository,
    database,
    session_scope,
)
from src.integrations.telegram import TelegramNotifier  # noqa: E402
from src.integrations.telegram_poller import poll_loop  # noqa: E402
from src.runtime import manager as runtime_manager  # noqa: E402
from src.runtime.approvals import resolve_approval  # noqa: E402
from src.security.sakshi import SakshiLog  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Telegram-клиент (MockTransport) ───────────────────────────────────

def _mock_transport(captured: list):
    def handler(request: httpx.Request) -> httpx.Response:
        body = {}
        if request.content:
            body = json.loads(request.content.decode())
        captured.append({"url": str(request.url), "body": body})
        if request.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 10, "callback_query": {"id": "cb1", "data": "approve:abc"}},
            ]})
        return httpx.Response(200, json={"ok": True})
    return httpx.MockTransport(handler)


def test_parse_callback():
    assert TelegramNotifier.parse_callback("approve:ap1") == ("approve", "ap1")
    assert TelegramNotifier.parse_callback("reject:ap2") == ("reject", "ap2")
    assert TelegramNotifier.parse_callback("nope") is None
    assert TelegramNotifier.parse_callback("approve:") is None


def test_send_approval_inline_keyboard():
    captured: list = []
    notifier = TelegramNotifier("TOKEN", "123", transport=_mock_transport(captured))
    _run(notifier.send_approval("ap-1", {"agent": "bot", "action": "transfer",
                                         "params": {"amount": 1}, "reasoning": "r"}))
    assert captured[0]["url"].endswith("/botTOKEN/sendMessage")
    buttons = captured[0]["body"]["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == "approve:ap-1"
    assert buttons[1]["callback_data"] == "reject:ap-1"


def test_get_updates_with_offset():
    captured: list = []
    notifier = TelegramNotifier("T", "1", transport=_mock_transport(captured))
    updates = _run(notifier.get_updates(offset=42))
    assert updates[0]["update_id"] == 10
    assert "offset=42" in captured[0]["url"]


class _FakeNotifier:
    def __init__(self, updates):
        self._updates = list(updates)
        self.answers: list = []
        self.sent: list = []

    async def get_updates(self, offset=None, timeout=25):
        return self._updates.pop(0) if self._updates else []

    async def answer_callback(self, callback_id, text):
        self.answers.append((callback_id, text))

    async def send_message(self, text, reply_markup=None):
        self.sent.append(text)


def test_poll_loop_processes_callback(monkeypatch):
    calls: list = []

    async def fake_resolve(approval_id, action, **kwargs):
        calls.append((approval_id, action))
        return {"status": "approved", "executed": True}

    monkeypatch.setattr("src.runtime.approvals.resolve_approval", fake_resolve)
    fake = _FakeNotifier([[{"update_id": 1,
                            "callback_query": {"id": "cb9", "data": "approve:apX"}}]])

    async def _run_loop():
        stop = asyncio.Event()
        task = asyncio.create_task(poll_loop(fake, stop))
        await asyncio.sleep(0.1)
        stop.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run_loop())
    assert calls == [("apX", "approve")]
    assert fake.answers and "Одобрено" in fake.answers[0][1]


# ── resolve_approval (сервис, с БД) ───────────────────────────────────

@pytest.fixture
def db_env():
    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    runtime_manager.reset()
    yield
    runtime_manager.reset()


async def _seed_approval():
    async with session_scope() as session:
        user = await UserRepository(session).create("tg-user", "h")
        agent = await AgentRepository(session).create(user.id, name="tg-agent")
        decision = await DecisionRepository(session).add(
            agent.id, action="transfer", params={"to": "0xabc", "amount": 0.5},
            reasoning="r", requires_approval=True,
        )
        approval = await ApprovalRepository(session).create(decision.id, channel="web")
        return str(user.id), str(agent.id), str(decision.id), str(approval.id)


class _FakeRuntime:
    def __init__(self):
        self.executed: list = []

    async def execute_intent(self, action, params):
        self.executed.append((action, params))
        return {"status": "confirmed", "tx_hash": "0x9"}


def test_resolve_approval_approve_executes_via_runtime(db_env):
    user_id, agent_id, _decision_id, approval_id = _run(_seed_approval())
    fake = _FakeRuntime()
    runtime_manager._runtimes[agent_id] = fake

    result = _run(resolve_approval(approval_id, "approve"))
    assert result["status"] == "approved" and result["executed"] is True
    assert fake.executed == [("transfer", {"to": "0xabc", "amount": 0.5})]

    again = _run(resolve_approval(approval_id, "approve"))
    assert "already" in again["error"]


def test_resolve_approval_reject_no_execution(db_env):
    _user_id, agent_id, _decision_id, approval_id = _run(_seed_approval())
    fake = _FakeRuntime()
    runtime_manager._runtimes[agent_id] = fake

    result = _run(resolve_approval(approval_id, "reject"))
    assert result["status"] == "rejected"
    assert result["executed"] is False
    assert fake.executed == []


# ── API (владелец, изоляция) ──────────────────────────────────────────

@pytest.fixture
def client_env():
    from src.api import main as main_module

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    runtime_manager.reset()
    with TestClient(main_module.app) as client:
        yield client
    runtime_manager.reset()


def _auth(client, username="appr-user") -> str:
    client.post("/api/v1/auth/register",
                json={"username": username, "password": "pass12345"})
    response = client.post("/api/v1/auth/token",
                           json={"username": username, "password": "pass12345"})
    return response.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_approvals_flow(client_env):
    client = client_env
    token = _auth(client)
    agent = client.post("/api/v1/agents", json={"name": "appr-agent"},
                        headers=_h(token)).json()
    agent_id = agent["id"]

    async def _seed():
        async with session_scope() as session:
            decision = await DecisionRepository(session).add(
                uuid.UUID(agent_id), action="transfer",
                params={"to": "0xabc", "amount": 0.5}, requires_approval=True,
            )
            return str((await ApprovalRepository(session).create(decision.id)).id)

    database.reset_engine()
    approval_id = _run(_seed())
    database.reset_engine()

    listing = client.get("/api/v1/approvals", headers=_h(token))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["approvals"][0]["action"] == "transfer"

    fake = _FakeRuntime()
    runtime_manager._runtimes[agent_id] = fake
    approved = client.post(f"/api/v1/approvals/{approval_id}/approve", headers=_h(token))
    assert approved.status_code == 200
    assert approved.json()["executed"] is True

    assert client.get("/api/v1/approvals", headers=_h(token)).json()["total"] == 0

    other = _auth(client, "other-user")
    other_view = client.get("/api/v1/approvals", headers=_h(other))
    assert other_view.json()["total"] == 0


# ── Ядро: тик поднимает approval и зовёт notifier ─────────────────────

def test_core_tick_raises_approval_with_notifier(db_env):
    async def _seed_agent():
        async with session_scope() as session:
            user = await UserRepository(session).create("core-user", "h")
            agent = await AgentRepository(session).create(user.id, name="core-agent")
            return user.id, agent.id

    user_id, agent_id = _run(_seed_agent())
    notifier_calls: list = []
    ws_events: list = []

    async def fake_notifier(approval_id, info):
        notifier_calls.append((approval_id, info))

    async def fake_sink(event):
        ws_events.append(event)

    agent = OnChainAgent(
        AgentConfig(name="core-appr", chain="sepolia"),
        db_agent_id=agent_id, sakshi=SakshiLog("test-key"),
        notifier=fake_notifier, event_sink=fake_sink,
    )

    async def fake_gather():
        return {"chain": "sepolia"}

    async def fake_decide(state, goal, history=None, temperature=0.3):
        return AgentDecision(action="transfer", params={"to": "0xabc", "amount": 0.5},
                             reasoning="needs approval", confidence=0.8,
                             risk_level="medium", requires_approval=True)

    agent._gather_state = fake_gather  # type: ignore[assignment]
    agent.reasoner.decide = fake_decide  # type: ignore[assignment]
    _run(agent._tick())

    assert agent.state.status == "awaiting_approval"
    assert notifier_calls and notifier_calls[0][0]  # approval_id
    assert any(e.get("type") == "approval.requested" for e in ws_events)

    async def _pending_count():
        async with session_scope() as session:
            return len(await ApprovalRepository(session).list_pending_with_decision(user_id))

    assert _run(_pending_count()) == 1
