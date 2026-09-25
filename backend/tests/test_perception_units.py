"""Юнит-тесты perception (fake w3, без сети): баланс/газ/receipt/monitor."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.perception import BlockchainPerception, MempoolMonitor  # noqa: E402


class FakeEth:
    block_number = 42
    gas_price = 30 * 10**9

    @staticmethod
    def get_balance(address):
        return 10**18

    @staticmethod
    def estimate_gas(tx):
        return 21000

    @staticmethod
    def get_transaction_receipt(tx_hash):
        return {"status": 1, "blockNumber": 42, "gasUsed": 21000, "logs": []}

    @staticmethod
    def get_block(_):
        return {"baseFeePerGas": 20 * 10**9, "number": 42}


class FakeW3:
    def __init__(self):
        self.eth = FakeEth()


def _perception_with_fake() -> BlockchainPerception:
    perception = BlockchainPerception(chains=[])  # без сети
    perception.connections["ethereum"] = FakeW3()
    return perception


def test_perception_reads():
    p = _perception_with_fake()
    assert p.get_block_number("ethereum") == 42
    assert p.get_balance("0x" + "ab" * 20) == 1.0
    assert p.get_gas_price("ethereum") == 30.0
    assert p.estimate_gas({}) == 21000
    receipt = p.get_transaction_receipt("0xabc")
    assert receipt and receipt["status"] == 1


def test_perception_unknown_chain_defaults():
    p = _perception_with_fake()
    assert p.get_web3("base") is None
    assert p.get_block_number("base") == 0
    assert p.get_balance("0x" + "ab" * 20, chain="base") == 0.0


def test_mempool_monitor_trend_and_status():
    p = _perception_with_fake()
    monitor = MempoolMonitor(p, history=5)
    monitor.watch("0x" + "ab" * 20)
    assert len(monitor._watched_addresses) == 1
    monitor.unwatch("0x" + "ab" * 20)
    assert monitor._watched_addresses == set()

    monitor._gas_history = [(1, 20.0), (2, 22.0), (3, 25.0)]
    assert monitor.gas_trend() in ("up", "down", "flat", "unknown")
    status = monitor.status()
    assert isinstance(status, dict) and "running" in status
