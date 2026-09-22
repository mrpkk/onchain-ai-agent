"""Тесты S1-05: approve-гигиена — только точные суммы, блок max-approve."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.execution import MAX_UINT256, SecurityError, TransactionExecutor  # noqa: E402


def test_exact_amount_converted_with_decimals():
    assert TransactionExecutor._to_approve_amount(18, 100.0) == 100 * 10**18
    assert TransactionExecutor._to_approve_amount(6, 50.0) == 50 * 10**6
    assert TransactionExecutor._to_approve_amount(18, 0.0) == 0


def test_none_amount_blocked():
    with pytest.raises(SecurityError) as exc:
        TransactionExecutor._to_approve_amount(18, None)
    assert exc.value.code == "AMOUNT_REQUIRED"


def test_negative_amount_blocked():
    with pytest.raises(SecurityError) as exc:
        TransactionExecutor._to_approve_amount(18, -1.0)
    assert exc.value.code == "NEGATIVE_AMOUNT"


def test_infinite_amount_blocked():
    with pytest.raises(SecurityError) as exc:
        TransactionExecutor._to_approve_amount(18, 1e60)
    assert exc.value.code == "INFINITE_APPROVE_BLOCKED"


def test_max_uint256_constant_is_single_definition():
    """2**256 встречается в модуле ровно один раз — в константе MAX_UINT256."""
    source = Path(__file__).resolve().parents[1].joinpath("src/agent/execution.py").read_text()
    assert source.count("2**256") == 1
    assert MAX_UINT256 == 2**256 - 1


def test_revoke_approve_uses_zero_amount(monkeypatch):
    calls = {}

    def fake_approve(token_address, spender, amount=None, chain="ethereum"):
        calls.update(token_address=token_address, spender=spender, amount=amount, chain=chain)
        return "result"

    executor = TransactionExecutor.__new__(TransactionExecutor)
    monkeypatch.setattr(executor, "approve_token", fake_approve)
    result = executor.revoke_approve("0xToken", "0xSpender", chain="sepolia")

    assert result == "result"
    assert calls == {
        "token_address": "0xToken",
        "spender": "0xSpender",
        "amount": 0.0,
        "chain": "sepolia",
    }
