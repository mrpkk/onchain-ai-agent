"""Юнит-тесты планировщика: шаги, зависимости, прогресс, генерация плана."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.planning import AgentPlanner, Plan, PlanStatus, PlanStep, StepType  # noqa: E402


def _plan() -> Plan:
    return Plan(id="p1", goal="test", steps=[
        PlanStep(id="s1", step_type=StepType.READ_STATE, description="read", chain="sepolia"),
        PlanStep(id="s2", step_type=StepType.TRANSFER, description="send", chain="sepolia",
                 params={"to": "0xabc", "amount": 0.1}, depends_on=["s1"]),
    ])


def test_progress_and_next_step_with_deps():
    plan = _plan()
    assert plan.progress == 0.0
    assert plan.get_next_step().id == "s1"  # s2 ждёт зависимость

    plan.steps[0].status = PlanStatus.COMPLETED
    assert plan.get_next_step().id == "s2"
    assert plan.progress == 0.5

    plan.steps[1].status = PlanStatus.COMPLETED
    assert plan.get_next_step() is None
    assert plan.is_done is True and plan.progress == 1.0


def test_failures_and_blocked_do_not_block_others():
    plan = _plan()
    plan.steps[0].status = PlanStatus.FAILED
    assert plan.has_failures is True
    # s2 зависит от s1 (не COMPLETED) → не выдаётся
    assert plan.get_next_step() is None

    plan2 = _plan()
    plan2.steps[0].status = PlanStatus.BLOCKED  # отложен timelock-ом
    assert plan2.get_next_step() is None  # зависимый шаг ждёт


def test_planner_create_plan():
    planner = AgentPlanner()
    plan = planner.create_plan("Проверь баланс и переведи 0.01 ETH", {"chain": "sepolia"})
    assert plan.id and plan.goal
    assert len(plan.steps) >= 1
    assert all(step.chain == "sepolia" for step in plan.steps)
