"""Тесты S4-10: Intent→Guarantee (NL-правило → политика) и Agent Health Score."""
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

from src.agent.policy_intent import (  # noqa: E402
    PolicyIntentSchema,
    _patch_from_rule,
    build_policy_yaml,
    parse_policy_rule,
)
from src.db import (  # noqa: E402
    AgentRepository,
    DecisionRepository,
    Transaction,
    UserRepository,
    database,
    session_scope,
)
from src.providers.llm import LLMResult, LLMRouter  # noqa: E402
from src.runtime.health_score import compute_health_score  # noqa: E402
from src.security.dharma import PolicyError, compile_yaml  # noqa: E402
from tests.test_llm_router import ScriptedProvider  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── Intent→Guarantee: unit ────────────────────────────────────────────

def test_patch_from_rule_limits():
    rule = PolicyIntentSchema(rule_type="limits",
                              params={"daily_eth": 0.05, "per_tx_eth": 0.01, "junk": 1})
    patch = _patch_from_rule(rule)
    assert patch == {"limits": {"per_tx_eth": 0.01, "daily_eth": 0.05}}


def test_patch_from_rule_deny_lowercases():
    rule = PolicyIntentSchema(rule_type="deny_addresses",
                              params={"addresses": ["0xABC"]})
    assert _patch_from_rule(rule) == {"deny": {"addresses": ["0xabc"]}}


def test_build_policy_yaml_merges_over_base():
    base = "limits: {per_tx_eth: 0.5, daily_eth: 2.0}\n"
    rule = PolicyIntentSchema(rule_type="limits", params={"daily_eth": 0.05})
    yaml_str, patch = build_policy_yaml(base, rule)
    compiled = compile_yaml(yaml_str)
    assert compiled.model.limits.daily_eth == 0.05
    assert compiled.model.limits.per_tx_eth == 0.5  # база сохранена
    assert patch == {"limits": {"daily_eth": 0.05}}


def test_build_policy_yaml_invalid_raises():
    rule = PolicyIntentSchema(rule_type="limits", params={"daily_eth": -1})
    with pytest.raises(PolicyError):
        build_policy_yaml("deny: {actions: [deploy]}\n", rule)


def test_build_policy_yaml_noop_raises():
    with pytest.raises(PolicyError):
        build_policy_yaml(None, PolicyIntentSchema(rule_type="noop"))


def test_parse_policy_rule_unit():
    payload = ('{"rule_type": "limits", "params": {"daily_eth": 0.05}, '
               '"summary": "лимит 0.05/день", "confidence": 0.9, '
               '"needs_clarification": false, "questions": []}')
    provider = ScriptedProvider("fake", [payload])
    schema, result = _run(parse_policy_rule("не трать больше 0.05 в день",
                                            router=LLMRouter([provider])))
    assert schema.rule_type == "limits"
    assert schema.params["daily_eth"] == 0.05
    assert result.provider == "fake"


# ── API: from-text (превью и применение) ─────────────────────────────

@pytest.fixture
def client_env(monkeypatch):
    from src.api import main as main_module

    database.reset_engine()
    _run(database.drop_all())
    _run(database.create_all())

    async def fake_parse(text, router=None):
        return PolicyIntentSchema(rule_type="limits", params={"daily_eth": 0.05},
                                  summary="лимит", confidence=0.9), LLMResult(text="", provider="fake")

    monkeypatch.setattr(main_module, "parse_policy_rule", fake_parse)
    with TestClient(main_module.app) as client:
        yield client, main_module, monkeypatch


def _auth(client) -> str:
    client.post("/api/v1/auth/register",
                json={"username": "pol-rule-user", "password": "pass12345"})
    return client.post("/api/v1/auth/token",
                       json={"username": "pol-rule-user", "password": "pass12345"}).json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_policy_from_text_preview_and_apply(client_env):
    client, _main, _mp = client_env
    token = _auth(client)
    agent_id = client.post("/api/v1/agents", json={"name": "rule-agent"},
                           headers=_h(token)).json()["id"]

    preview = client.post(f"/api/v1/agents/{agent_id}/policy/from-text",
                          json={"text": "не трать больше 0.05 в день"}, headers=_h(token))
    assert preview.status_code == 200
    body = preview.json()
    assert body["ok"] is True
    assert body["patch"] == {"limits": {"daily_eth": 0.05}}
    assert body["dsl_yaml"]

    applied = client.put(f"/api/v1/agents/{agent_id}/policy",
                         json={"dsl_yaml": body["dsl_yaml"]}, headers=_h(token))
    assert applied.status_code == 200
    policy = client.get(f"/api/v1/agents/{agent_id}/policy", headers=_h(token)).json()
    assert policy["compiled"]["model"]["limits"]["daily_eth"] == 0.05


def test_policy_from_text_clarification(client_env):
    client, main_module, monkeypatch = client_env
    token = _auth(client)
    agent_id = client.post("/api/v1/agents", json={"name": "rule-agent-2"},
                           headers=_h(token)).json()["id"]

    async def clarify_parse(text, router=None):
        return PolicyIntentSchema(rule_type="noop", needs_clarification=True,
                                  questions=["Какой лимит?"]), LLMResult(text="", provider="f")

    monkeypatch.setattr(main_module, "parse_policy_rule", clarify_parse)
    response = client.post(f"/api/v1/agents/{agent_id}/policy/from-text",
                           json={"text": "сделай безопасно"}, headers=_h(token))
    assert response.status_code == 200
    assert response.json()["needs_clarification"] is True
    assert response.json()["dsl_yaml"] is None


# ── Health Score ──────────────────────────────────────────────────────

def test_health_score_components_and_band():
    async def _seed():
        async with session_scope() as session:
            user = await UserRepository(session).create("health-user", "h")
            agent = await AgentRepository(session).create(user.id, name="health-agent")
            repo = DecisionRepository(session)
            for _ in range(4):
                await repo.add(agent.id, action="transfer", reasoning="d",
                               policy_verdict={"decision": "deny"})
            for _ in range(2):
                row = await repo.add(agent.id, action="transfer", reasoning="f")
                row.status = "failed"
            session.add(Transaction(agent_id=agent.id, status="confirmed", chain_id=1))
            session.add(Transaction(agent_id=agent.id, status="failed", chain_id=1))
            return agent.id

    agent_id = _run(_seed())

    async def _health():
        async with session_scope() as session:
            return await compute_health_score(session, agent_id)

    report = _run(_health())
    # penalty: denies 4*5=20, failed 2*5=10, tx 1/2*30=15 → 45 → score 55
    assert report["score"] == 55
    assert report["band"] == "degraded"
    assert report["components"]["policy_denials"] == 4
    assert report["components"]["transactions_failed"] == 1
    assert report["recommendation"]


def test_summary_includes_health(client_env):
    client, _main, _mp = client_env
    token = _auth(client)
    agent_id = client.post("/api/v1/agents", json={"name": "health-agent-2"},
                           headers=_h(token)).json()["id"]
    response = client.get(f"/api/v1/agents/{agent_id}/reports/summary", headers=_h(token))
    assert response.status_code == 200
    body = response.json()
    assert body["health"]["score"] == 100  # без событий — здоров
    assert body["health"]["band"] == "healthy"
