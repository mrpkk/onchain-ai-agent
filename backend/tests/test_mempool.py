"""Тесты S2-07: MempoolMonitor — фильтрация tx, газ-тренд, честный отказ без RPC."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.perception import MempoolMonitor  # noqa: E402

WATCHED = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20


def _block(transactions, base_fee_gwei: float = 20.0) -> dict:
    return {
        "transactions": transactions,
        "baseFeePerGas": int(base_fee_gwei * 10**9),
    }


def _tx(sender: str, receiver: str, value_wei: int = 10**18) -> dict:
    return {"from": sender, "to": receiver, "value": value_wei, "input": "0x", "hash": b"\x01" * 32}


class _FakeEth:
    def __init__(self, blocks: dict, gas_price: int = 10**9):
        self._blocks = blocks
        self.block_number = max(blocks) if blocks else 0
        self.gas_price = gas_price

    def get_block(self, number: int, full_transactions: bool = False) -> dict:
        return self._blocks[number]


class _FakeW3:
    def __init__(self, blocks: dict, gas_price: int = 10**9):
        self.eth = _FakeEth(blocks, gas_price)


class _FakePerception:
    def __init__(self, w3):
        self._w3 = w3

    def get_web3(self, chain: str):
        return self._w3


def _run(coro):
    return asyncio.run(coro)


def test_scan_filters_watched_addresses():
    blocks = {
        102: _block([_tx(WATCHED, OTHER), _tx(OTHER, OTHER), _tx(OTHER, WATCHED)]),
    }
    monitor = MempoolMonitor(_FakePerception(_FakeW3(blocks)))
    monitor.watch(WATCHED)

    result = _run(monitor.scan_once("ethereum"))
    assert result["ok"] is True
    assert result["scanned_blocks"] == 1
    assert len(result["found"]) == 2  # from-WATCHED и to-WATCHED
    assert monitor.status()["recent_matched"] == 2


def test_scan_skips_old_blocks_after_first_pass():
    blocks = {
        102: _block([_tx(WATCHED, OTHER)]),
    }
    fake = _FakeW3(blocks)  # current block = 102
    monitor = MempoolMonitor(_FakePerception(fake))
    monitor.watch(WATCHED)

    first = _run(monitor.scan_once("ethereum"))
    assert first["scanned_blocks"] == 1  # только текущий блок

    fake.eth._blocks[103] = _block([_tx(WATCHED, OTHER)])
    fake.eth.block_number = 103
    second = _run(monitor.scan_once("ethereum"))
    assert second["scanned_blocks"] == 1  # только новый блок
    assert monitor.blocks_scanned == 2


def test_no_rpc_is_honest():
    monitor = MempoolMonitor(_FakePerception(None))
    result = _run(monitor.scan_once("ethereum"))
    assert result == {"ok": False, "reason": "rpc_unavailable", "found": [], "scanned_blocks": 0}
    assert monitor.status()["last_block"] is None


def test_unwatch_removes_address():
    blocks = {102: _block([_tx(WATCHED, OTHER)])}
    monitor = MempoolMonitor(_FakePerception(_FakeW3(blocks)))
    monitor.watch(WATCHED)
    monitor.unwatch(WATCHED)
    result = _run(monitor.scan_once("ethereum"))
    assert result["found"] == []


def test_gas_trend_up_from_blocks():
    blocks = {
        101: _block([], base_fee_gwei=10),
        102: _block([], base_fee_gwei=30),
        103: _block([], base_fee_gwei=50),
    }
    fake = _FakeW3(blocks)
    monitor = MempoolMonitor(_FakePerception(fake))
    monitor.watch(WATCHED)
    _run(monitor.scan_once("ethereum"))  # 103 (первый проход)
    fake.eth.block_number = 104
    fake.eth._blocks[104] = _block([], base_fee_gwei=52)
    _run(monitor.scan_once("ethereum"))
    # наполним историю вручную для стабильности тренда
    monitor._gas_history = [(1, 10.0), (2, 12.0), (3, 30.0)]
    assert monitor.gas_trend() == "up"
    monitor._gas_history = [(1, 30.0), (2, 20.0), (3, 10.0)]
    assert monitor.gas_trend() == "down"
    monitor._gas_history = [(1, 20.0), (2, 21.0), (3, 20.5)]
    assert monitor.gas_trend() == "flat"
    monitor._gas_history = []
    assert monitor.gas_trend() == "unknown"


def test_status_shape():
    monitor = MempoolMonitor(_FakePerception(None))
    status = monitor.status()
    assert status["implemented"] is True
    assert status["running"] is False
    assert status["watched_addresses"] == 0
    assert status["gas_trend"] == "unknown"
