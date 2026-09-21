"""Тесты S3-05: Approval Guardian — классификация allowances и план revoke."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.guardian import MAX_UINT256, ApprovalGuardian  # noqa: E402

TOKEN_A = "0x" + "aa" * 20
TOKEN_B = "0x" + "bb" * 20
TOKEN_C = "0x" + "cc" * 20
TOKEN_ERR = "0x" + "dd" * 20
SPENDER = "0x" + "ee" * 20
BLOCKED = "0x" + "ff" * 20


class _Fn:
    def __init__(self, value):
        self._value = value

    def call(self):
        return self._value


class _Functions:
    def __init__(self, decimals, raw):
        self._decimals = _Fn(decimals)
        self._raw = _Fn(raw)

    def decimals(self):
        return self._decimals

    def allowance(self, owner, spender):
        return self._raw


class _Contract:
    def __init__(self, decimals, raw):
        self.functions = _Functions(decimals, raw)


class _Eth:
    def __init__(self, mapping):
        self._mapping = mapping

    def contract(self, address, abi):
        value = self._mapping[address]
        if isinstance(value, Exception):
            raise value
        return _Contract(*value)


class _FakeW3:
    def __init__(self, mapping):
        self.eth = _Eth(mapping)


def test_classify_rules():
    guardian = ApprovalGuardian(review_threshold=1000, blocked_spenders=[BLOCKED])
    assert guardian.classify(MAX_UINT256, 1e60, SPENDER)[0] == "HIGH_RISK"
    assert guardian.classify(10, 10, BLOCKED)[0] == "HIGH_RISK"
    assert guardian.classify(0, 0, SPENDER)[0] == "SAFE"
    assert guardian.classify(1500 * 10**18, 1500.0, SPENDER)[0] == "REVIEW"
    assert guardian.classify(10 * 10**18, 10.0, SPENDER)[0] == "SAFE"


def test_scan_mixed_allowances():
    w3 = _FakeW3({
        TOKEN_A: (18, MAX_UINT256),
        TOKEN_B: (6, 500 * 10**6),
        TOKEN_C: (18, 0),
    })
    guardian = ApprovalGuardian(review_threshold=1000)
    reports = guardian.scan(w3, "0xowner", [(TOKEN_A, SPENDER), (TOKEN_B, SPENDER), (TOKEN_C, SPENDER)])
    risks = [r.risk for r in reports]
    assert risks == ["HIGH_RISK", "SAFE", "SAFE"]
    assert reports[0].reasons


def test_scan_read_error_is_review():
    w3 = _FakeW3({TOKEN_ERR: ValueError("no contract")})
    guardian = ApprovalGuardian()
    report = guardian.scan(w3, "0xowner", [(TOKEN_ERR, SPENDER)])[0]
    assert report.risk == "REVIEW"
    assert "не удалось прочитать" in report.reasons[0]


def test_build_revoke_plan_filters_safe():
    guardian = ApprovalGuardian(review_threshold=1000, blocked_spenders=[BLOCKED])
    w3 = _FakeW3({
        TOKEN_A: (18, MAX_UINT256),
        TOKEN_B: (18, 2000 * 10**18),
        TOKEN_C: (18, 1 * 10**18),
    })
    reports = guardian.scan(w3, "0xowner",
                            [(TOKEN_A, SPENDER), (TOKEN_B, SPENDER), (TOKEN_C, SPENDER)])
    plan = guardian.build_revoke_plan(reports)
    assert (TOKEN_A, SPENDER) in plan and (TOKEN_B, SPENDER) in plan
    assert (TOKEN_C, SPENDER) not in plan


def test_report_to_dict_shape():
    report = ApprovalGuardian().scan(_FakeW3({TOKEN_C: (18, 0)}), "0xowner",
                                     [(TOKEN_C, SPENDER)])[0]
    data = report.to_dict()
    assert set(data) == {"token", "spender", "allowance_raw", "allowance_human", "risk", "reasons"}
    assert data["allowance_raw"] == "0"
