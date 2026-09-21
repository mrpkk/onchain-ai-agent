"""Регрессия тика (найдено E2E-смоуком): _tick не должен падать на current_plan."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.planning import Plan, PlanStatus, PlanStep, StepType  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _agent() -> OnChainAgent:
    agent = OnChainAgent(AgentConfig(name="tick-reg", chain="sepolia"))

    async def fake_gather_state():
        return {"chain": "sepolia", "block_number": 0}

    agent._gather_state = fake_gather_state  # type: ignore[assignment]
    return agent


def test_tick_with_plan_does_not_crash():
    agent = _agent()
    plan = Plan(id="p1", goal="regression", steps=[
        PlanStep(id="s1", step_type=StepType.READ_STATE, description="read",
                 chain="sepolia"),
    ])
    agent.state.current_plan = plan

    _run(agent._tick())  # раньше: AttributeError 'current_plan'

    assert plan.steps[0].status == PlanStatus.COMPLETED


def test_tick_decision_path_records_diary():
    agent = _agent()

    async def fake_decide(state, goal, history=None, temperature=0.3):
        return AgentDecision(action="hold", params={}, reasoning="regression",
                             confidence=0.5, risk_level="low")

    agent.reasoner.decide = fake_decide  # type: ignore[assignment]
    _run(agent._tick())

    events = [e["event"] for e in agent._audit_log]
    assert "decision_made" in events
    assert agent.state.last_action is not None
