"""Конверт задачи — бюджет принадлежит задаче, а не вызову (SPEC v4 §6.1).

Детерминированный слой политики: без БД, без сети, без LLM. Один и тот же
evaluator используют демо, API и MCP, поэтому вердикт всегда одной формы:
``verdict / rule / reason / counterfactual / next``.

Идентификаторы правил стабильны: E01…E07. Их нельзя переименовывать — на них
ссылаются квитанции и evidence-пакеты.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

ALLOW = "ALLOW"
HOLD = "HOLD"
BLOCK = "BLOCK"


@dataclass(frozen=True)
class Envelope:
    """Один конверт на одну задачу агента."""

    budget_total: Decimal
    per_call_max: Decimal
    calls_max: int
    allowlist: tuple[str, ...] = ()
    allow_new_payee: bool = False
    allow_subscriptions: bool = False
    approval_threshold: Decimal | None = None
    expires_at: datetime | None = None
    envelope_id: str = ""

    def __post_init__(self) -> None:
        if not self.envelope_id:
            object.__setattr__(self, "envelope_id", f"env_{uuid.uuid4().hex[:16]}")
        if self.budget_total < 0 or self.per_call_max < 0:
            raise ValueError("бюджет не может быть отрицательным")
        if self.calls_max < 0:
            raise ValueError("calls_max не может быть отрицательным")

    def allows_payee(self, payee: str) -> bool:
        """Регистронезависимое совпадение по домену или полному адресу."""
        target = payee.strip().lower()
        return any(target == a.lower() or target.endswith("." + a.lower()) for a in self.allowlist)


@dataclass(frozen=True)
class SpendRequest:
    """Намерение потратить: то, что агент просит, но не исполняет сам."""

    amount: Decimal
    payee: str
    calls_so_far: int = 0
    spent_so_far: Decimal = Decimal("0")
    is_subscription: bool = False
    now: datetime | None = None


@dataclass(frozen=True)
class Verdict:
    verdict: str
    rule: str
    reason: str
    counterfactual: str
    next: str

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "rule": self.rule,
            "reason": self.reason,
            "counterfactual": self.counterfactual,
            "next": self.next,
        }


def _allow() -> Verdict:
    return Verdict(ALLOW, "E00", "within_envelope", "—", "execute")


def evaluate(env: Envelope, req: SpendRequest) -> Verdict:
    """Порядок проверок фиксирован: сначала то, что нельзя обойти деньгами."""
    now = req.now or datetime.now(timezone.utc)

    if env.expires_at is not None and now >= env.expires_at:
        return Verdict(BLOCK, "E01", "envelope_expired",
                       f"envelope expired at {env.expires_at.isoformat()}",
                       "open_new_envelope")

    if req.is_subscription and not env.allow_subscriptions:
        return Verdict(BLOCK, "E02", "subscription_not_permitted",
                       "subscriptions are not permitted by this envelope; a one-off payment would pass",
                       "owner_approval_or_new_envelope")

    if not env.allows_payee(req.payee):
        if env.allow_new_payee:
            return Verdict(HOLD, "E03", "payee_not_in_allowlist",
                           f"{req.payee} is not in allowlist {list(env.allowlist)}",
                           "owner_approval")
        return Verdict(BLOCK, "E03", "payee_not_allowed",
                       f"{req.payee} is not in allowlist {list(env.allowlist)}; new payees are not permitted",
                       "owner_approval_or_new_envelope")

    if req.amount > env.per_call_max:
        return Verdict(BLOCK, "E04", "per_call_exceeded",
                       f"{req.amount} exceeds per-call limit {env.per_call_max}",
                       "split_request_or_new_envelope")

    if req.calls_so_far >= env.calls_max:
        return Verdict(BLOCK, "E05", "calls_exhausted",
                       f"{env.calls_max} calls permitted, requested call #{req.calls_so_far + 1} ({req.calls_so_far / max(env.calls_max,1):.1f}x the cap)",
                       "close_task")

    projected = req.spent_so_far + req.amount
    if projected > env.budget_total:
        return Verdict(BLOCK, "E06", "budget_exceeded",
                       f"spent {req.spent_so_far} + {req.amount} exceeds budget {env.budget_total}",
                       "close_task_or_new_envelope")

    if env.approval_threshold is not None and req.amount >= env.approval_threshold:
        return Verdict(HOLD, "E07", "above_approval_threshold",
                       f"{req.amount} is at or above approval threshold {env.approval_threshold}",
                       "owner_approval")

    return _allow()
