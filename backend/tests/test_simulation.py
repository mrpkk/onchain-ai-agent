"""Тесты S3-02: Simulation-гейт — без свежего ok-receipt исполнения нет."""
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
from src.agent.simulation import SimulationReceipt, SimulationService  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── SimulationService (eth_call движок) ───────────────────────────────

class _FakeEth:
    def __init__(self, call_error=None, estimate_error=None, block=100):
        self._call_error = call_error
        self._estimate_error = estimate_error
        self.block_number = block

    def call(self, tx):
        if self._call_error:
            raise self._call_error
        return b"\x01"

    def estimate_gas(self, tx):
        if self._estimate_error:
            raise self._estimate_error
        return 21000


class _FakeW3:
    def __init__(self, **kwargs):
        self.eth = _FakeEth(**kwargs)


def test_simulate_success_receipt():
    service = SimulationService()
    receipt = service.simulate_tx(_FakeW3(), {"from": "0x1", "to": "0x2", "value": 1})
    assert receipt.ok is True
    assert receipt.gas_estimate == 21000
    assert receipt.engine == "eth_call"
    assert receipt.fork_block == 100
    assert receipt.warnings  # честная пометка про engine
    assert receipt.is_fresh() is True


def test_simulate_revert_receipt():
    service = SimulationService()
    receipt = service.simulate_tx(
        _FakeW3(call_error=ValueError("execution reverted: insufficient balance")),
        {"from": "0x1", "to": "0x2", "value": 1},
    )
    assert receipt.ok is False
    assert "reverted" in (receipt.revert_reason or "")


def test_simulate_estimate_failure_receipt():
    service = SimulationService()
    receipt = service.simulate_tx(
        _FakeW3(estimate_error=ValueError("gas estimation failed")),
        {"from": "0x1", "to": "0x2", "value": 1},
    )
    assert receipt.ok is False
    assert "estimate_gas failed" in (receipt.revert_reason or "")


def test_receipt_freshness():
    old = SimulationReceipt(ok=True, created_at=datetime.now(timezone.utc) - timedelta(seconds=300))
    assert old.is_fresh() is False
    fresh = SimulationReceipt(ok=True)
    assert fresh.is_fresh() is True
    assert fresh.to_dict()["engine"] == "eth_call"


# ── Гейт в ядре ───────────────────────────────────────────────────────

class _SpyExecutor:
    def __init__(self):
        self.calls: list[dict] = []

    def send_eth(self, **kwargs):
        self.calls.append(kwargs)
        return TransactionResult(
            tx_hash="0xdeadbeef", status=TxStatus.CONFIRMED, chain="sepolia",
            from_address="0x0", to_address=kwargs.get("to_address", ""),
            value=kwargs.get("amount_eth", 0), gas_used=21000, gas_price_gwei=1,
        )


def _agent_with_spy(sim_result):
    agent = OnChainAgent(AgentConfig(name="sim-test", chain="sepolia"))
    spy = _SpyExecutor()
    agent.executor = spy
    agent._simulate = lambda action, params: sim_result  # noqa: ARG005
    return agent, spy


def _decision():
    return AgentDecision(action="transfer", params={"to": "0xabc", "amount": 0.1},
                         reasoning="sim", confidence=0.9, risk_level="low")


def test_execution_blocked_when_simulation_reverts():
    receipt = SimulationReceipt(ok=False, revert_reason="execution reverted: nope")
    agent, spy = _agent_with_spy(receipt)
    result = _run(agent._execute_decision(_decision()))
    assert result.status == TxStatus.FAILED
    assert "Simulation failed" in result.error
    assert spy.calls == []
    events = [e["event"] for e in agent._audit_log]
    assert "simulation_failed" in events


def test_execution_blocked_when_simulation_unavailable():
    agent, spy = _agent_with_spy(None)
    result = _run(agent._execute_decision(_decision()))
    assert result.status == TxStatus.FAILED
    assert "Simulation unavailable" in result.error
    assert spy.calls == []


def test_execution_blocked_on_stale_receipt():
    stale = SimulationReceipt(ok=True,
                              created_at=datetime.now(timezone.utc) - timedelta(seconds=500))
    agent, spy = _agent_with_spy(stale)
    result = _run(agent._execute_decision(_decision()))
    assert result.status == TxStatus.FAILED
    assert "stale" in result.error
    assert spy.calls == []


def test_execution_proceeds_after_successful_simulation():
    receipt = SimulationReceipt(ok=True, gas_estimate=21000)
    agent, spy = _agent_with_spy(receipt)
    result = _run(agent._execute_decision(_decision()))
    assert result.status == TxStatus.CONFIRMED
    assert len(spy.calls) == 1
    events = [e["event"] for e in agent._audit_log]
    assert "simulation_passed" in events
    assert agent.state.last_simulation is not None


def test_build_sim_tx_mapping():
    agent = OnChainAgent(AgentConfig(name="tx-build", chain="sepolia"))

    class _Wallet:
        address = "0x" + "ab" * 20

    agent.wallet = _Wallet()
    transfer = agent._build_sim_tx("transfer", {"to": "0x" + "cd" * 20, "amount": 0.5})
    assert transfer["value"] == int(0.5 * 10**18)
    assert transfer["to"].lower() == "0x" + "cd" * 20

    approve = agent._build_sim_tx("approve", {"token": "0x" + "ee" * 20, "amount": 1})
    assert approve["value"] == 0
    assert approve["to"].lower() == "0x" + "ee" * 20

    assert agent._build_sim_tx("transfer", {}) is None
    assert agent._build_sim_tx("hold", {}) is None
