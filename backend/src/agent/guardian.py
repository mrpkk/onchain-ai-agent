"""Approval Guardian — сканер ERC-20 allowances (SPEC S3-05).

Классификация: SAFE | REVIEW | HIGH_RISK. Рекомендации revoke — для REVIEW/HIGH_RISK.
Честное ограничение: полное on-chain-перечисление approvals невозможно без
индексатора — сканируются известные пары (token, spender) агента.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

MAX_UINT256 = 2**256 - 1

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True,
     "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


@dataclass
class AllowanceReport:
    token: str
    spender: str
    allowance_raw: int
    allowance_human: float
    risk: str  # SAFE | REVIEW | HIGH_RISK
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "spender": self.spender,
            "allowance_raw": str(self.allowance_raw),
            "allowance_human": self.allowance_human,
            "risk": self.risk,
            "reasons": self.reasons,
        }


class ApprovalGuardian:
    """Классификация и рекомендации по allowances."""

    def __init__(self, review_threshold: float = 1000.0,
                 blocked_spenders: Iterable[str] = ()):
        self.review_threshold = review_threshold
        self.blocked_spenders = {s.lower() for s in blocked_spenders}

    def classify(self, allowance_raw: int, allowance_human: float,
                 spender: str) -> tuple[str, list[str]]:
        if spender.lower() in self.blocked_spenders:
            return "HIGH_RISK", ["spender в чёрном списке"]
        if allowance_raw >= MAX_UINT256:
            return "HIGH_RISK", ["бесконечный allowance (2^256-1) — рекомендуется revoke"]
        if allowance_raw == 0:
            return "SAFE", []
        if allowance_human >= self.review_threshold:
            return "REVIEW", [f"крупный allowance ≥ {self.review_threshold}"]
        return "SAFE", []

    def scan(self, w3, owner: str,
             pairs: Sequence[tuple[str, str]]) -> list[AllowanceReport]:
        """Сканирует известные пары (token, spender). Ошибки чтения → REVIEW (честно)."""
        reports: list[AllowanceReport] = []
        for token, spender in pairs:
            try:
                contract = w3.eth.contract(address=token, abi=ERC20_ABI)
                decimals = int(contract.functions.decimals().call())
                raw = int(contract.functions.allowance(owner, spender).call())
            except Exception as e:  # noqa: BLE001
                reports.append(AllowanceReport(
                    token=token, spender=spender, allowance_raw=-1,
                    allowance_human=0.0, risk="REVIEW",
                    reasons=[f"не удалось прочитать: {type(e).__name__}"],
                ))
                continue
            human = raw / (10 ** decimals) if decimals else float(raw)
            risk, reasons = self.classify(raw, human, spender)
            reports.append(AllowanceReport(token=token, spender=spender,
                                           allowance_raw=raw, allowance_human=human,
                                           risk=risk, reasons=reasons))
        return reports

    @staticmethod
    def build_revoke_plan(reports: Sequence[AllowanceReport]) -> list[tuple[str, str]]:
        """Пары (token, spender), которые стоит отозвать (REVIEW/HIGH_RISK)."""
        return [(r.token, r.spender) for r in reports if r.risk in ("REVIEW", "HIGH_RISK")]
