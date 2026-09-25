"""Тесты S3-03: Timelock/undo-window — отложенные действия, отмена, исполнение по сроку."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.agent.execution import TransactionResult, TxStatus  # noqa: E402
from src.agent.reasoning import AgentDecision  # noqa: E402
from src.agent.simulation import SimulationReceipt  # noqa: E402
from src.agent.timelock import TimelockQueue  # noqa: E402
from src.security.dharma import build_default_policy, compile_policy  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _SpyExecutor:
    def __init__(self):
        self.calls: list[dict] = []

    def send_eth(self, **kwargs):
        self.calls.append(kwargs)
        return TransactionResult(
            tx_hash="0xfeed", status=TxStatus.CONFIRMED, chain="sepolia",
            from_address="0x0", to_address=kwargs.get("to_address", ""),
            value=kwargs.get("amount_eth", 0), gas_used=21000, gas_price_gwei=1,
        )


def _agent(policy=None):
    agent = OnChainAgent(AgentConfig(name="tl-test", chain="sepolia"),
                         policy=policy or build_default_policy(1.0, 5.0))
    spy = _SpyExecutor()
    agent.executor = spy
    agent._simulate = lambda action, params: SimulationReceipt(ok=True, gas_estimate=21000)  # noqa: ARG005
    return agent, spy


def _decision(amount: float = 0.1):
    return AgentDecision(action="transfer", params={"to": "0xabc", "amount": amount},
                         reasoning="tl", confidence=0.9, risk_level="low")


def _undo_policy(window: int = 300, threshold: float = 0.05):
    return compile_policy({
        "limits": {"per_tx_eth": 1.0, "daily_eth": 5.0},
        "undo": {"window_seconds": window, "threshold_eth": threshold},
    })


# ── Очередь ───────────────────────────────────────────────────────────

def test_queue_schedule_cancel_due():
    queue = TimelockQueue()
    now = datetime.now(timezone.utc)
    item = queue.schedule("transfer", {"to": "0x1"}, 60, now=now)
    assert item.execute_after == now + timedelta(seconds=60)
    assert len(queue.pending()) == 1
    assert queue.due(now=now) == []
    assert queue.due(now=now + timedelta(seconds=61)) == [item]

    assert queue.cancel(item.id) is True
    assert queue.pending() == []
    assert queue.cancel(item.id) is False  # повторная отмена


# ── Гейт в ядре ───────────────────────────────────────────────────────

def test_no_undo_section_executes_immediately():
    agent, spy = _agent(build_default_policy(1.0, 5.0))  # undo.window=0 по умолчанию
    result = _run(agent._execute_decision(_decision()))
    assert result.status == TxStatus.CONFIRMED
    assert len(spy.calls) == 1


def test_action_scheduled_instead_of_execution():
    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    result = _run(agent._execute_decision(_decision(0.1)))
    assert result.status == TxStatus.PENDING
    assert spy.calls == []  # не исполнено
    pending = agent.timelock.pending()
    assert len(pending) == 1 and pending[0].action == "transfer"
    assert agent.state.status == "awaiting_undo"
    events = [e["event"] for e in agent._audit_log]
    assert "action_scheduled" in events


def test_below_threshold_executes_immediately():
    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    result = _run(agent._execute_decision(_decision(0.01)))
    assert result.status == TxStatus.CONFIRMED
    assert len(spy.calls) == 1


def test_cancel_prevents_execution():
    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    _run(agent._execute_decision(_decision(0.1)))
    item = agent.timelock.pending()[0]
    assert agent.cancel_pending(item.id) is True

    item.execute_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    _run(agent._process_due_actions())
    assert spy.calls == []  # отменённое не исполняется


def test_due_action_executes_after_window():
    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    _run(agent._execute_decision(_decision(0.1)))
    item = agent.timelock.pending()[0]

    item.execute_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    _run(agent._process_due_actions())

    assert len(spy.calls) == 1  # исполнено после окна
    assert item.status == "executed"
    events = [e["event"] for e in agent._audit_log]
    assert "timelock_executed" in events


def test_due_action_blocked_by_kill_switch():
    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    _run(agent._execute_decision(_decision(0.1)))
    item = agent.timelock.pending()[0]
    item.execute_after = datetime.now(timezone.utc) - timedelta(seconds=1)

    agent.trigger_kill_switch(mode="hard")
    _run(agent._process_due_actions())
    assert spy.calls == []
    assert item.status == "pending"


# ── Plan-step путь (долг S3-03) ──────────────────────────────────────

def test_plan_step_scheduled_with_undo_and_completed_after_window():
    from src.agent.planning import Plan, PlanStatus, PlanStep, StepType

    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    plan = Plan(id="p1", goal="tl-plan", steps=[
        PlanStep(id="s1", step_type=StepType.TRANSFER, description="send",
                 chain="sepolia", params={"to": "0xabc", "amount": 0.1}),
    ])
    agent.state.current_plan = plan

    _run(agent._execute_plan_step())
    step = plan.steps[0]
    assert step.status == PlanStatus.BLOCKED  # отложен, не исполнен
    assert spy.calls == []
    pending = agent.timelock.pending()
    assert len(pending) == 1 and pending[0].params.get("_plan_step_id") == "s1"

    pending[0].execute_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    _run(agent._process_due_actions())

    assert len(spy.calls) == 1  # исполнено после окна
    assert step.status == PlanStatus.COMPLETED  # шаг закрыт
    assert pending[0].status == "executed"


def test_plan_step_below_threshold_executes_immediately():
    from src.agent.planning import Plan, PlanStatus, PlanStep, StepType

    agent, spy = _agent(_undo_policy(window=300, threshold=0.05))
    plan = Plan(id="p2", goal="tl-plan-2", steps=[
        PlanStep(id="s1", step_type=StepType.TRANSFER, description="send-small",
                 chain="sepolia", params={"to": "0xabc", "amount": 0.01}),
    ])
    agent.state.current_plan = plan

    _run(agent._execute_plan_step())
    assert plan.steps[0].status == PlanStatus.COMPLETED
    assert len(spy.calls) == 1
    assert agent.timelock.pending() == []
