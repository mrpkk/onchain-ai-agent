"""Тесты S4-03: chat-first — NL→intent, Dharma-превью, подтверждение, исполнение через гейты."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.execution import TransactionResult, TxStatus  # noqa: E402
from src.agent.intent import IntentSchema, parse_intent  # noqa: E402
from src.agent.simulation import SimulationReceipt  # noqa: E402
from src.db import database  # noqa: E402
from src.providers.llm import AllProvidersFailed, LLMResult, LLMRouter  # noqa: E402
from tests.test_llm_router import ScriptedProvider  # noqa: E402

BAD = "0x" + "ba" * 20
GOOD = "0x" + "ab" * 20


def _run(coro):
    return asyncio.run(coro)


# ── unit: NL-парсер ───────────────────────────────────────────────────

def test_parse_intent_unit():
    payload = ('{"action": "transfer", "params": {"to": "%s", "amount": 0.01}, '
               '"summary": "перевод 0.01", "confidence": 0.9, "assumptions": [], '
               '"needs_clarification": false, "questions": []}') % GOOD
    provider = ScriptedProvider("good", [payload])
    schema, result = _run(parse_intent("переведи 0.01 на 0xab…", router=LLMRouter([provider])))
    assert schema.action == "transfer"
    assert schema.params["amount"] == 0.01
    assert result.provider == "good"


# ── API: превью и подтверждение ───────────────────────────────────────

class FakeRuntime:
    def __init__(self):
        self.intents: list[tuple] = []
        self._stop = None

    async def start(self):
        self._stop = asyncio.Event()
        await self._stop.wait()

    async def stop(self):
        if self._stop is not None:
            self._stop.set()

    async def execute_intent(self, action, params):
        self.intents.append((action, params))
        return {"status": "confirmed", "tx_hash": "0xintent", "error": None}

    def trigger_kill_switch(self, **kwargs):
        pass

    def heartbeat(self):
        pass


@pytest.fixture
def env(monkeypatch):
    from src.api import main as main_module
    from src.runtime import manager as runtime_manager

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())
    runtime_manager.reset()

    created: dict[str, FakeRuntime] = {}

    async def fake_build(agent_row, *, event_sink=None, **kwargs):
        runtime = FakeRuntime()
        created[str(agent_row.id)] = runtime
        return runtime

    monkeypatch.setattr(main_module, "build_agent", fake_build)

    async def fake_parse(text, router=None):
        return IntentSchema(
            action="transfer", params={"to": GOOD, "amount": 0.01},
            summary="перевод", confidence=0.9,
        ), LLMResult(text="{}", provider="fake")

    monkeypatch.setattr(main_module, "parse_intent", fake_parse)
    with TestClient(main_module.app) as client:
        yield client, created, main_module, monkeypatch
    runtime_manager.reset()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _auth(client) -> str:
    client.post("/api/v1/auth/register",
                json={"username": "chat-user", "password": "pass12345"})
    response = client.post("/api/v1/auth/token",
                           json={"username": "chat-user", "password": "pass12345"})
    return response.json()["access_token"]


def _agent(client, token) -> str:
    response = client.post("/api/v1/agents",
                           json={"name": "chat-agent", "chain_id": 11155111},
                           headers=_h(token))
    return response.json()["id"]


def test_intent_preview_allow(env):
    client, _created, _main, _mp = env
    token = _auth(client)
    agent_id = _agent(client, token)

    response = client.post(f"/api/v1/agents/{agent_id}/intent",
                           json={"text": "переведи 0.01 ETH"}, headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["intent"]["action"] == "transfer"
    assert body["policy_verdict"]["decision"] == "allow"
    assert body["warnings"]


def test_intent_preview_deny_blacklisted(env):
    client, _created, _main, _mp = env
    token = _auth(client)
    agent_id = _agent(client, token)
    client.put(f"/api/v1/agents/{agent_id}/policy",
               json={"dsl_yaml": f"deny: {{addresses: ['{BAD}']}}\n"}, headers=_h(token))

    _main.parse_intent_orig = _main.parse_intent

    async def parse_bad(text, router=None):
        return IntentSchema(action="transfer", params={"to": BAD, "amount": 0.01},
                            summary="bad", confidence=0.9), LLMResult(text="", provider="fake")

    _mp.setattr(_main, "parse_intent", parse_bad)
    response = client.post(f"/api/v1/agents/{agent_id}/intent",
                           json={"text": "переведи на bad"}, headers=_h(token))
    assert response.status_code == 200
    assert response.json()["policy_verdict"]["decision"] == "deny"


def test_intent_preview_llm_unavailable(env):
    client, _created, main_module, monkeypatch = env
    token = _auth(client)
    agent_id = _agent(client, token)

    async def failing_parse(text, router=None):
        raise AllProvidersFailed({"gigachat": "down", "deepseek": "down"})

    monkeypatch.setattr(main_module, "parse_intent", failing_parse)
    response = client.post(f"/api/v1/agents/{agent_id}/intent",
                           json={"text": "переведи"}, headers=_h(token))
    assert response.status_code == 503
    assert "LLM unavailable" in response.json()["detail"]


def test_intent_confirm_requires_running_agent(env):
    client, _created, _main, _mp = env
    token = _auth(client)
    agent_id = _agent(client, token)
    response = client.post(f"/api/v1/agents/{agent_id}/intent/confirm",
                           json={"action": "transfer", "params": {"to": GOOD, "amount": 0.01}},
                           headers=_h(token))
    assert response.status_code == 409


def test_intent_confirm_executes_through_runtime(env):
    client, created, _main, _mp = env
    token = _auth(client)
    agent_id = _agent(client, token)
    client.post(f"/api/v1/agents/{agent_id}/start", headers=_h(token))

    response = client.post(f"/api/v1/agents/{agent_id}/intent/confirm",
                           json={"action": "transfer", "params": {"to": GOOD, "amount": 0.01}},
                           headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["tx_hash"] == "0xintent"
    assert created[agent_id].intents == [("transfer", {"to": GOOD, "amount": 0.01})]


# ── unit: execute_intent (полный контур) ──────────────────────────────

class _SpyExecutor:
    def __init__(self):
        self.calls = []

    def send_eth(self, **kwargs):
        self.calls.append(kwargs)
        return TransactionResult(tx_hash="0xspy", status=TxStatus.CONFIRMED, chain="sepolia",
                                 from_address="0x0", to_address=kwargs.get("to_address", ""),
                                 value=kwargs.get("amount_eth", 0), gas_used=21000,
                                 gas_price_gwei=1)


def test_execute_intent_without_wallet_is_honest():
    agent = OnChainAgent(AgentConfig(name="chat-nw", chain="sepolia"))
    result = _run(agent.execute_intent("transfer", {"to": GOOD, "amount": 0.01}))
    assert result["status"] == "failed"
    assert "Wallet not configured" in result["error"]


def test_execute_intent_confirms_with_spy():
    agent = OnChainAgent(AgentConfig(name="chat-spy", chain="sepolia"))
    spy = _SpyExecutor()
    agent.executor = spy
    agent._simulate = lambda action, params: SimulationReceipt(ok=True, gas_estimate=21000)  # noqa: ARG005
    result = _run(agent.execute_intent("transfer", {"to": GOOD, "amount": 0.01}))
    assert result["status"] == "confirmed"
    assert len(spy.calls) == 1


def test_execute_intent_respects_timelock():
    from src.security.dharma import compile_policy

    policy = compile_policy({"undo": {"window_seconds": 300, "threshold_eth": 0.005}})
    agent = OnChainAgent(AgentConfig(name="chat-tl", chain="sepolia"), policy=policy)
    spy = _SpyExecutor()
    agent.executor = spy
    agent._simulate = lambda action, params: SimulationReceipt(ok=True, gas_estimate=21000)  # noqa: ARG005
    result = _run(agent.execute_intent("transfer", {"to": GOOD, "amount": 0.01}))
    assert result["status"] == "pending"  # отложено в окно undo
    assert spy.calls == []
    assert len(agent.timelock.pending()) == 1
