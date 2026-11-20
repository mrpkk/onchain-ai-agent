"""S4: x402-guard останавливает цикл на границе бюджета задачи.

Сценарий из SPEC v4 §2.2 в миниатюре: агент платит по 402 за каждый вызов,
каждый платёж корректен. Задача — чтобы на границе конверта поток встал,
а не «через 41 000 вызовов».
"""

import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-x402-")) / "ledger.db")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import pytest  # noqa: E402

from src.security import ledger, x402  # noqa: E402

ledger.init()

CHALLENGE = {"accepts": [{
    "scheme": "exact", "network": "eip155:8453", "asset": "USDC",
    "amount": "10000", "payTo": "0xabc", "resource": "https://api.example.com/search",
    "decimals": 6,
}]}


def _open(budget: str, per_call: str = "0.01", calls: int = 100000) -> str:
    return ledger.create(budget_total=Decimal(budget), per_call_max=Decimal(per_call),
                         calls_max=calls, allowlist=("api.example.com",),
                         ttl_hours=2)["envelope_id"]


def test_challenge_amount_is_converted_from_atomic_units():
    challenge = x402.parse_challenge(CHALLENGE)
    assert challenge.amount == Decimal("0.01")
    assert challenge.payee == "api.example.com"  # allowlist сверяется по хосту


def test_runaway_loop_stops_at_the_envelope_boundary():
    eid = _open("5.00")
    challenge = x402.parse_challenge(CHALLENGE)
    verdicts = []
    for _ in range(1000):
        verdict, _ = ledger.reserve(eid, amount=challenge.amount, payee=challenge.payee)
        verdicts.append(verdict.verdict)

    assert verdicts.count("ALLOW") == 500
    assert verdicts.count("BLOCK") == 500
    state = ledger.get(eid)
    assert state["spent"] == "5.00"
    assert state["remaining"] == "0.00"


def test_unknown_vendor_is_refused_before_payment():
    eid = _open("5.00")
    challenge = x402.parse_challenge({"amount": "1000000", "payTo": "0xevil",
                                      "resource": "https://evil.example/x"})
    verdict, receipt = ledger.reserve(eid, amount=challenge.amount, payee=challenge.payee)
    assert verdict.rule == "E03" and receipt is None
    assert ledger.get(eid)["spent"] == "0"


def test_broken_challenge_is_an_error_not_a_guess():
    for payload in ({}, {"accepts": []}, {"amount": "abc", "resource": "https://x/y"}):
        with pytest.raises(x402.ChallengeError):
            x402.parse_challenge(payload)
