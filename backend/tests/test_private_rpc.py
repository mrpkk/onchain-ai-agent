"""Тесты S5-05: private RPC (mainnet-only, fallback) + jitter."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.execution import (  # noqa: E402
    SpendingLimit,
    TransactionExecutor,
    TxStatus,
)
from src.agent.gas_oracle import GasOracle, GasRecommendation  # noqa: E402


class StubOracle(GasOracle):
    def recommend(self, w3, force=False):
        return GasRecommendation(chain_id=1, base_fee_gwei=20, priority_fee_gwei=2,
                                 max_fee_gwei=42, block_number=1, source="base+priority")


class FakeWallet:
    address = "0x" + "ab" * 20

    def get_nonce(self, w3):
        return 0

    def sign_transaction(self, w3, tx):
        return b"raw-tx"


class FakeEth:
    def __init__(self, chain_id):
        self.chain_id = chain_id
        self.sent = []

    def send_raw_transaction(self, raw_tx):
        self.sent.append(raw_tx)
        return b"\x01\x02"

    @property
    def gas_price(self):
        return 25 * 10**9


class FakeBlock:
    number = 100
    baseFeePerGas = 20 * 10**9


class FakeW3:
    def __init__(self, chain_id=1, fail_send=False):
        self.eth = FakeEth(chain_id)
        self.fail_send = fail_send
        if fail_send:
            def _boom(_):
                raise ConnectionError("private relay down")
            self.eth.send_raw_transaction = _boom

    @staticmethod
    def to_wei(value, unit):
        return int(value * 10**18)

    @staticmethod
    def to_checksum_address(address):
        return address


def _executor(chain_id=1, private_w3=None, jitter=0.0):
    executor = TransactionExecutor(
        wallet=FakeWallet(),
        w3=FakeW3(chain_id),
        spending_limit=SpendingLimit(daily_limit=1.0, per_tx_limit=1.0),
        gas_oracle=StubOracle(),
        private_w3=private_w3,
        jitter_max_seconds=jitter,
    )
    executor._wait_for_receipt = lambda tx_hash, chain: {
        "status": 1, "gas_used": 21000, "block_number": 1,
    }
    return executor


def test_private_rpc_used_on_mainnet():
    private = FakeW3()
    executor = _executor(chain_id=1, private_w3=private)
    result = executor.send_eth("0x" + "cd" * 20, 0.001)
    assert result.status == TxStatus.CONFIRMED
    assert result.submit_via == "private"
    assert len(private.eth.sent) == 1


def test_private_rpc_fallback_on_error():
    private = FakeW3(fail_send=True)
    executor = _executor(chain_id=1, private_w3=private)
    result = executor.send_eth("0x" + "cd" * 20, 0.001)
    assert result.status == TxStatus.CONFIRMED
    assert result.submit_via == "public"


def test_private_rpc_skipped_on_testnet():
    private = FakeW3()
    executor = _executor(chain_id=11155111, private_w3=private)
    result = executor.send_eth("0x" + "cd" * 20, 0.001)
    assert result.status == TxStatus.CONFIRMED
    assert result.submit_via == "public"
    assert private.eth.sent == []  # private (mainnet-релей) на тестнете не используется


def test_jitter_applied(monkeypatch):
    import src.agent.execution as execution

    slept = []
    monkeypatch.setattr(execution.random, "uniform", lambda a, b: 1.0)
    monkeypatch.setattr(execution.time, "sleep", lambda s: slept.append(s))

    executor = _executor(jitter=1.5)
    executor.send_eth("0x" + "cd" * 20, 0.001)
    assert slept == [1.0]


def test_jitter_disabled(monkeypatch):
    import src.agent.execution as execution

    slept = []
    monkeypatch.setattr(execution.time, "sleep", lambda s: slept.append(s))
    executor = _executor(jitter=0.0)
    executor.send_eth("0x" + "cd" * 20, 0.001)
    assert slept == []


def test_health_reports_private_rpc_disabled():
    from fastapi.testclient import TestClient

    from src.api import main as main_module
    from src.db import database

    database.reset_engine()
    with TestClient(main_module.app) as client:
        body = client.get("/api/v1/health").json()
    assert body["components"]["private_rpc"]["status"] == "disabled"
