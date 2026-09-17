"""Тесты S1-08: kill-switch drill — после kill исполнение невозможно, auto-resume нет."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.planning import Plan, PlanStatus, PlanStep, StepType  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402


@pytest.fixture
def agent(monkeypatch):
    a = OnChainAgent(AgentConfig(name="kill-drill", chain="sepolia"))
    monkeypatch.setattr(a.perception, "get_gas_price", lambda chain: 20.0)
    return a


def _decision():
    return AgentDecision(action="transfer", params={"to": "0xabc", "amount": 0.1},
                         reasoning="drill", confidence=0.9, risk_level="low")


def test_hard_kill_blocks_decision(agent):
    agent.trigger_kill_switch(mode="hard", reason="drill")
    result = asyncio.run(agent._execute_decision(_decision()))
    assert result.status.value == "failed"
    assert "Kill switch" in result.error
    events = [e["event"] for e in agent._audit_log]
    assert "kill_switch" in events and "kill_switch_block" in events


def test_soft_kill_blocks_decision(agent):
    agent.trigger_kill_switch(mode="soft", reason="drill")
    result = asyncio.run(agent._execute_decision(_decision()))
    assert result.status.value == "failed"
    assert "Kill switch" in result.error


def test_hard_kill_blocks_plan_step(agent):
    agent.trigger_kill_switch(mode="hard")
    plan = Plan(id="p1", goal="drill", steps=[
        PlanStep(id="s1", step_type=StepType.TRANSFER, description="t",
                 chain="sepolia", params={"to": "0xabc", "amount": 0.1}),
    ])
    agent.state.current_plan = plan
    asyncio.run(agent._execute_plan_step())
    assert plan.steps[0].status == PlanStatus.FAILED
    assert "Kill switch" in plan.steps[0].error


def test_config_kill_switch_blocks_execution():
    a = OnChainAgent(AgentConfig(name="kill-config", chain="sepolia", kill_switch=True))
    result = asyncio.run(a._execute_decision(_decision()))
    assert result.status.value == "failed"
    assert "Kill switch" in result.error


def test_hard_kill_is_terminal_no_auto_resume(agent):
    agent.trigger_kill_switch(mode="hard")
    assert agent.config.kill_switch is True
    assert agent.state.status == "killed"
    # никакого авто-возобновления: повторные вызовы исполнения — всё ещё блок
    result = asyncio.run(agent._execute_decision(_decision()))
    assert "Kill switch" in result.error
    assert agent.state.status == "killed"
