"""Тесты Dharma Engine (S1-06): компилятор, все правила, гейт в путях исполнения."""
import asyncio
import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent import core as core_module  # noqa: E402
from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.planning import Plan, PlanStatus, PlanStep, StepType  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402
from src.security.dharma import (  # noqa: E402
    DenyReason,
    PolicyError,
    TxContext,
    VerdictDecision,
    build_default_policy,
    compile_policy,
    compile_yaml,
    evaluate,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
BAD = "0xbad0000000000000000000000000000000000000"


def make_policy(**overrides):
    data = {
        "version": 1,
        "limits": {"per_tx_eth": 1.0, "daily_eth": 2.0,
                   "velocity": {"window_min": 10, "max_tx": 3},
                   "gas_gwei_cap": 60, "slippage_bps_max": 50},
        "allow": {"actions": ["transfer", "contract_call", "approve", "hold", "swap"],
                  "chains": [1, 137]},
        "deny": {"actions": ["deploy"], "addresses": [BAD]},
        "approvals": {"required_if": {"risk_score_gte": 0.6, "amount_eth_gte": 0.25,
                                      "new_spender": True}, "ttl_min": 30},
        "circuit_breakers": {"anomaly_score_gte": 0.8, "revert_streak_gte": 3},
    }
    data.update(overrides)
    return compile_policy(data)


def make_ctx(**overrides):
    params = {"to": "0xabc", "amount": 0.1}
    params.update(overrides.pop("params", {}))
    defaults = dict(action="transfer", params=params, chain_id=1, gas_price_gwei=20.0, now_utc=NOW)
    defaults.update(overrides)
    return TxContext(**defaults)


# ── Компилятор ────────────────────────────────────────────────────────

def test_compile_yaml_ok():
    policy = compile_yaml("version: 1\nlimits: {per_tx_eth: 0.5, daily_eth: 1.0}\n")
    assert policy.model.limits.per_tx_eth == 0.5
    assert policy.model.limits.daily_eth == 1.0


def test_bad_yaml_raises():
    with pytest.raises(PolicyError):
        compile_yaml("version: [unclosed")


def test_unknown_field_rejected():
    with pytest.raises(PolicyError):
        compile_policy({"version": 1, "unknown_thing": True})


def test_window_parsed():
    policy = make_policy(active_utc="08:00-22:00")
    assert policy.window == (480, 1320)


def test_bad_window_rejected():
    with pytest.raises(PolicyError):
        make_policy(active_utc="25:00-26:00")


def test_default_policy_denies_deploy():
    verdict = evaluate(build_default_policy(1.0, 5.0), make_ctx(action="deploy", params={}))
    assert verdict.decision == VerdictDecision.DENY


# ── Правила evaluator ─────────────────────────────────────────────────

def test_happy_path_allows():
    verdict = evaluate(make_policy(), make_ctx())
    assert verdict.decision == VerdictDecision.ALLOW


def test_denied_action():
    verdict = evaluate(make_policy(), make_ctx(action="deploy", params={}))
    assert verdict.decision == VerdictDecision.DENY
    assert "deny.actions" in verdict.rule_ids


def test_action_not_allowed():
    verdict = evaluate(make_policy(), make_ctx(action="bridge", params={}))
    assert verdict.decision == VerdictDecision.DENY
    assert "allow.actions" in verdict.rule_ids


def test_chain_not_allowed():
    verdict = evaluate(make_policy(), make_ctx(chain_id=56))
    assert verdict.decision == VerdictDecision.DENY
    assert "allow.chains" in verdict.rule_ids


def test_unknown_chain_failsafe():
    verdict = evaluate(make_policy(), make_ctx(chain_id=None))
    assert verdict.decision == VerdictDecision.DENY


def test_blacklisted_address():
    verdict = evaluate(make_policy(), make_ctx(params={"to": BAD}))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.blacklisted_address in verdict.codes


def test_whitelist_only_mode():
    policy = make_policy(allow={"actions": ["transfer"], "chains": [1],
                                "addresses": ["0xgood"]})
    denied = evaluate(policy, make_ctx())
    assert denied.decision == VerdictDecision.DENY
    assert "allow.addresses" in denied.rule_ids

    allowed = evaluate(policy, make_ctx(params={"to": "0xGOOD"}))
    assert allowed.decision == VerdictDecision.ALLOW


def test_per_tx_limit():
    verdict = evaluate(make_policy(), make_ctx(params={"amount": 1.5}))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.over_per_tx_limit in verdict.codes


def test_daily_limit():
    verdict = evaluate(make_policy(), make_ctx(spent_today_eth=1.95))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.over_daily_limit in verdict.codes


def test_velocity_limit():
    recent = [NOW - timedelta(minutes=m) for m in (1, 2, 3)]
    verdict = evaluate(make_policy(), make_ctx(recent_tx=recent))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.over_velocity in verdict.codes


def test_slippage_limit():
    verdict = evaluate(make_policy(), make_ctx(action="swap",
                                               params={"slippage_bps": 100}))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.slippage_exceeded in verdict.codes


def test_infinite_approve_none_blocked():
    verdict = evaluate(make_policy(), make_ctx(action="approve", params={"spender": "0xS", "amount": None}))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.infinite_approve in verdict.codes


def test_infinite_approve_max_blocked():
    verdict = evaluate(make_policy(), make_ctx(action="approve",
                                               params={"spender": "0xS", "amount": 2**256 - 1}))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.infinite_approve in verdict.codes


def test_gas_cap_requires_approval():
    verdict = evaluate(make_policy(), make_ctx(gas_price_gwei=100.0))
    assert verdict.decision == VerdictDecision.REQUIRE_APPROVAL
    assert DenyReason.gas_cap_exceeded in verdict.codes


def test_time_window_closed():
    policy = make_policy(active_utc="08:00-22:00")
    late = NOW.replace(hour=23)
    verdict = evaluate(policy, make_ctx(now_utc=late))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.time_window_closed in verdict.codes


def test_time_window_open():
    policy = make_policy(active_utc="08:00-22:00")
    verdict = evaluate(policy, make_ctx())
    assert verdict.decision == VerdictDecision.ALLOW


def test_anomaly_breaker():
    verdict = evaluate(make_policy(), make_ctx(anomaly_score=0.9))
    assert verdict.decision == VerdictDecision.DENY
    assert DenyReason.anomaly_detected in verdict.codes


def test_revert_streak_breaker():
    verdict = evaluate(make_policy(), make_ctx(revert_streak=3))
    assert verdict.decision == VerdictDecision.DENY
    assert "circuit_breakers.revert_streak_gte" in verdict.rule_ids


def test_approval_risk_score():
    verdict = evaluate(make_policy(), make_ctx(risk_score=0.7))
    assert verdict.decision == VerdictDecision.REQUIRE_APPROVAL


def test_approval_amount():
    verdict = evaluate(make_policy(), make_ctx(params={"amount": 0.3}))
    assert verdict.decision == VerdictDecision.REQUIRE_APPROVAL


def test_approval_new_spender():
    verdict = evaluate(make_policy(), make_ctx(new_spender=True))
    assert verdict.decision == VerdictDecision.REQUIRE_APPROVAL


# ── Интеграция: гейт в путях исполнения ───────────────────────────────

@pytest.fixture
def agent(monkeypatch):
    a = OnChainAgent(AgentConfig(name="dharma-test", chain="sepolia"))
    monkeypatch.setattr(a.perception, "get_gas_price", lambda chain: 20.0)
    return a


def _decision(action="transfer", params=None, risk="low"):
    return AgentDecision(action=action, params=params or {"to": "0xabc", "amount": 0.1},
                         reasoning="test", confidence=0.9, risk_level=risk)


def test_decision_denied_by_policy(agent):
    agent.policy = make_policy(deny={"actions": ["deploy", "transfer"]})
    result = asyncio.run(agent._execute_decision(_decision()))
    assert result.status.value == "failed"
    assert "Policy" in result.error
    assert any(e["event"] == "policy_verdict" for e in agent._audit_log)


def test_decision_requires_approval(agent):
    agent.policy = make_policy(
        allow={"actions": ["transfer"], "chains": [11155111]},
        approvals={"required_if": {
            "risk_score_gte": 0.6, "amount_eth_gte": 0.01, "new_spender": False}})
    result = asyncio.run(agent._execute_decision(_decision()))
    assert result.status.value == "failed"
    assert "require_approval" in result.error
    assert agent.state.status == "awaiting_approval"


def test_plan_step_denied_by_policy(agent):
    agent.policy = make_policy(deny={"actions": ["deploy", "transfer"]})
    plan = Plan(id="p1", goal="test", steps=[
        PlanStep(id="s1", step_type=StepType.TRANSFER, description="t",
                 chain="sepolia", params={"to": "0xabc", "amount": 0.1}),
    ])
    agent.state.current_plan = plan
    asyncio.run(agent._execute_plan_step())
    step = plan.steps[0]
    assert step.status == PlanStatus.FAILED
    assert "Policy denied" in step.error


def test_all_execution_paths_use_gate():
    """Ни один путь исполнения не минует Dharma-гейт."""
    source = inspect.getsource(core_module)
    assert source.count("_policy_gate(") >= 3  # def + decision + plan step


def test_dharma_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DHARMA_ENFORCE", "off")
    a = OnChainAgent(AgentConfig(name="off-test", chain="sepolia"))
    assert a._policy_gate("transfer", {"to": "0xabc", "amount": 100.0}) is None
