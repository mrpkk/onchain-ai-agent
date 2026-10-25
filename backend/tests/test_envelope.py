"""S1: конверт задачи — вердикт детерминирован, порядок правил не обходится.

Четыре сценария демо (SPEC v4 §8) и границы: истечение, порог подтверждения,
новый получатель при `allow_new_payee`.
"""

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.security.envelope import Envelope, SpendRequest, evaluate  # noqa: E402

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def _env(**kw) -> Envelope:
    base = dict(budget_total=Decimal("50"), per_call_max=Decimal("0.05"),
                calls_max=2000, allowlist=("api.example.com",),
                expires_at=NOW + timedelta(days=2))
    base.update(kw)
    return Envelope(**base)


def _req(**kw) -> SpendRequest:
    base = dict(amount=Decimal("0.05"), payee="api.example.com", now=NOW)
    base.update(kw)
    return SpendRequest(**base)


def test_runaway_calls_are_stopped_by_task_budget_not_per_call_limit():
    verdict = evaluate(_env(), _req(calls_so_far=41000, spent_so_far=Decimal("2050")))
    assert (verdict.verdict, verdict.rule) == ("BLOCK", "E05")
    assert "41001" in verdict.counterfactual


def test_unknown_payee_is_blocked():
    verdict = evaluate(_env(), _req(payee="reports-vendor.xyz", amount=Decimal("940")))
    assert (verdict.verdict, verdict.rule) == ("BLOCK", "E03")


def test_unknown_payee_holds_when_new_payees_need_approval():
    verdict = evaluate(_env(allow_new_payee=True), _req(payee="reports-vendor.xyz"))
    assert (verdict.verdict, verdict.rule) == ("HOLD", "E03")


def test_subscription_is_blocked_even_within_budget():
    verdict = evaluate(_env(), _req(amount=Decimal("9"), is_subscription=True))
    assert (verdict.verdict, verdict.rule) == ("BLOCK", "E02")


def test_normal_call_inside_envelope_is_allowed():
    verdict = evaluate(_env(), _req(amount=Decimal("0.04"), calls_so_far=15,
                                    spent_so_far=Decimal("0.75")))
    assert verdict.verdict == "ALLOW"


def test_budget_and_per_call_and_expiry():
    assert evaluate(_env(budget_total=Decimal("1")),
                    _req(spent_so_far=Decimal("0.99"))).rule == "E06"
    assert evaluate(_env(per_call_max=Decimal("0.01")), _req()).rule == "E04"
    assert evaluate(_env(expires_at=NOW - timedelta(seconds=1)), _req()).rule == "E01"


def test_approval_threshold_holds():
    verdict = evaluate(_env(approval_threshold=Decimal("25"), per_call_max=Decimal("100")),
                       _req(amount=Decimal("30")))
    assert (verdict.verdict, verdict.rule) == ("HOLD", "E07")


def test_demo_scenarios_match_documented_verdicts():
    """Сценарии страницы демо обязаны давать те же вердикты, что описаны в SPEC."""
    from src.demo.app import SCENARIOS

    expected = {"runaway": "E05", "new_payee": "E03",
                "subscription": "E02", "allow": "E00"}
    for sid, rule in expected.items():
        scenario = SCENARIOS[sid]
        assert evaluate(scenario["envelope"], scenario["request"]).rule == rule, sid


def test_same_input_same_verdict():
    env, req = _env(), _req()
    assert evaluate(env, req).to_dict() == evaluate(env, req).to_dict()
