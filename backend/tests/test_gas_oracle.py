"""Тесты S5-04: EIP-1559 газ-оракул, кап политики, executor с type-2 полями."""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.execution import (  # noqa: E402
    SpendingLimit,
    TransactionExecutor,
    TransactionResult,
    TxStatus,
)
from src.agent.gas_oracle import (  # noqa: E402
    GWEI,
    GasOracle,
    GasOracleError,
    GasRecommendation,
    ensure_within_cap,
)

# ── fake RPC ─────────────────────────────────────────────────────────

class FakeBlock:
    def __init__(self, number, base_fee):
        self.number = number
        self.baseFeePerGas = base_fee


class FakeEth:
    def __init__(self, chain_id=1, base_fee=20 * 10**9, gas_price=25 * 10**9, priority=2 * 10**9):
        self.chain_id = chain_id
        self._base_fee = base_fee
        self._gas_price = gas_price
        self._priority = priority
        self.block_calls = 0

    def get_block(self, _):
        self.block_calls += 1
        return FakeBlock(100, self._base_fee)

    @property
    def gas_price(self):
        return self._gas_price

    @property
    def max_priority_fee(self):
        if self._priority is None:
            raise AttributeError("eth_maxPriorityFeePerGas not supported")
        return self._priority


class FakeW3:
    def __init__(self, **kwargs):
        self.eth = FakeEth(**kwargs)


def test_oracle_math_base_plus_priority():
    oracle = GasOracle()
    rec = oracle.recommend(FakeW3())
    assert rec.base_fee_gwei == 20.0
    assert rec.priority_fee_gwei == 2.0
    assert rec.max_fee_gwei == 42.0  # 20×2 + 2
    assert rec.source == "base+priority"


def test_oracle_priority_fallback_and_floor():
    oracle = GasOracle()
    rec = oracle.recommend(FakeW3(priority=None, gas_price=27 * 10**9))
    assert rec.priority_fee_gwei == 7.0  # gasPrice - base

    rec2 = GasOracle().recommend(FakeW3(priority=0, gas_price=21 * 10**9))
    assert rec2.priority_fee_gwei == 1.0  # floor


def test_oracle_legacy_fallback():
    oracle = GasOracle()
    rec = oracle.recommend(FakeW3(base_fee=None, gas_price=30 * 10**9))
    assert rec.source == "gasPrice-fallback"
    assert rec.max_fee_gwei == 30.0
    assert oracle.fee_fields(rec) == {"gasPrice": 30 * 10**9}


def test_oracle_cache_ttl():
    oracle = GasOracle(ttl_sec=60)
    w3 = FakeW3()
    oracle.recommend(w3)
    oracle.recommend(w3)
    assert w3.eth.block_calls == 1  # второй вызов из кэша

    oracle.recommend(w3, force=True)
    assert w3.eth.block_calls == 2


def test_oracle_rpc_error():
    class BrokenW3:
        class eth:
            @staticmethod
            def get_block(_):
                raise ConnectionError("no route")

            @staticmethod
            def gas_price():
                raise ConnectionError("no route")

    with pytest.raises(GasOracleError) as err:
        GasOracle().recommend(BrokenW3())
    assert err.value.code == "RPC_UNAVAILABLE"


def test_ensure_within_cap():
    rec = GasRecommendation(chain_id=1, base_fee_gwei=20, priority_fee_gwei=2,
                            max_fee_gwei=42, block_number=1, source="base+priority")
    ensure_within_cap(rec, 0)    # кап выключен
    ensure_within_cap(rec, 50)   # выше рекомендации
    with pytest.raises(GasOracleError) as err:
        ensure_within_cap(rec, 40)
    assert err.value.code == "GAS_CAP_EXCEEDED"


def test_fee_fields_eip1559():
    oracle = GasOracle()
    rec = GasRecommendation(chain_id=1, base_fee_gwei=20, priority_fee_gwei=2,
                            max_fee_gwei=42, block_number=1, source="base+priority")
    fields = oracle.fee_fields(rec)
    assert fields["type"] == 2
    assert fields["maxFeePerGas"] == int(42 * GWEI)
    assert fields["maxPriorityFeePerGas"] == int(2 * GWEI)


# ── executor ─────────────────────────────────────────────────────────

class StubOracle(GasOracle):
    def __init__(self, rec):
        super().__init__()
        self._rec = rec

    def recommend(self, w3, force=False):
        return self._rec


class FakeWallet:
    address = "0x" + "ab" * 20

    def get_nonce(self, w3):
        return 0


class ExecW3:
    class eth:
        chain_id = 1

    @staticmethod
    def to_wei(value, unit):
        return int(value * 10**18)

    @staticmethod
    def to_checksum_address(address):
        return address


def _rec(max_fee_gwei=42.0):
    return GasRecommendation(chain_id=1, base_fee_gwei=20, priority_fee_gwei=2,
                             max_fee_gwei=max_fee_gwei, block_number=1,
                             source="base+priority")


def _executor(rec, cap=0):
    return TransactionExecutor(
        wallet=FakeWallet(),
        w3=ExecW3(),
        spending_limit=SpendingLimit(daily_limit=1.0, per_tx_limit=1.0),
        gas_oracle=StubOracle(rec),
        gas_cap_gwei=cap,
    )


def test_executor_refuses_above_gas_cap():
    executor = _executor(_rec(max_fee_gwei=500), cap=100)
    result = executor.send_eth("0x" + "cd" * 20, 0.001)
    assert result.status == TxStatus.FAILED
    assert "GAS_CAP_EXCEEDED" in (result.error or "")


def test_executor_builds_eip1559_tx():
    executor = _executor(_rec(max_fee_gwei=42))
    captured = {}

    def fake_retry(tx, value_eth, to_address, chain):
        captured.update(tx)
        return TransactionResult(
            tx_hash="0xdead", status=TxStatus.CONFIRMED, chain=chain,
            from_address=FakeWallet.address, to_address=to_address,
            value=value_eth, gas_used=21000, gas_price_gwei=42.0,
        )

    executor._execute_with_retry = fake_retry  # type: ignore[assignment]
    result = executor.send_eth("0x" + "cd" * 20, 0.001)
    assert result.status == TxStatus.CONFIRMED
    assert captured["type"] == 2
    assert captured["maxFeePerGas"] == int(42 * GWEI)
    assert captured["maxPriorityFeePerGas"] == int(2 * GWEI)
    assert "gasPrice" not in captured
