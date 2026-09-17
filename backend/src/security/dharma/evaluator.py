"""Evaluator Dharma — чистая детерминированная функция оценки (SPEC S1-06).

Инвариант: LLM предлагает — Dharma разрешает. Ни одно исполняемое действие
не проходит мимо evaluate(). Функция не делает сетевых вызовов и не зависит от LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .ctx import TxContext
from .dsl import CompiledPolicy

MAX_UINT256 = 2**256 - 1


class VerdictDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class DenyReason(str, Enum):
    blacklisted_address = "blacklisted_address"
    over_per_tx_limit = "over_per_tx_limit"
    over_daily_limit = "over_daily_limit"
    over_velocity = "over_velocity"
    gas_cap_exceeded = "gas_cap_exceeded"
    slippage_exceeded = "slippage_exceeded"
    not_in_whitelist = "not_in_whitelist"
    infinite_approve = "infinite_approve"
    time_window_closed = "time_window_closed"
    anomaly_detected = "anomaly_detected"


@dataclass
class Verdict:
    decision: VerdictDecision
    reasons: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    codes: list[DenyReason] = field(default_factory=list)
    policy_version: int = 1

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "reasons": self.reasons,
            "rule_ids": self.rule_ids,
            "codes": [c.value for c in self.codes],
            "policy_version": self.policy_version,
        }


def _deny(code: DenyReason, rule: str, message: str, version: int) -> Verdict:
    return Verdict(VerdictDecision.DENY, [message], [rule], [code], version)


def _window_open(now_min: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= now_min < end
    return now_min >= start or now_min < end  # окно через полночь


def evaluate(policy: CompiledPolicy, ctx: TxContext) -> Verdict:
    """Детерминированная оценка действия: allow | deny | require_approval."""
    m = policy.model
    version = policy.version
    action = ctx.action
    value = ctx.value_eth()

    # 1. Запрещённые действия
    if action in m.deny.actions:
        return _deny(DenyReason.not_in_whitelist, "deny.actions",
                     f"Действие '{action}' запрещено политикой", version)

    # 2. Действие должно быть в разрешённом наборе
    if action not in m.allow.actions:
        return _deny(DenyReason.not_in_whitelist, "allow.actions",
                     f"Действие '{action}' не разрешено политикой", version)

    # 3. Сети (fail-safe: неизвестная цепь при заданном списке → deny)
    if m.allow.chains is not None and (ctx.chain_id is None or ctx.chain_id not in m.allow.chains):
        return _deny(DenyReason.not_in_whitelist, "allow.chains",
                     f"Сеть {ctx.chain_id} не в разрешённом списке", version)

    # 4. Чёрный список адресов
    for addr in ctx.addresses():
        if addr in m.deny.addresses:
            return _deny(DenyReason.blacklisted_address, "deny.addresses",
                         f"Адрес {addr[:10]}… в чёрном списке", version)

    # 5. Whitelist-режим (если задан непустой список)
    if m.allow.addresses:
        recipient = (ctx.params.get("to") or ctx.params.get("address")
                     or ctx.params.get("contract") or "")
        if recipient and str(recipient).lower() not in m.allow.addresses:
            return _deny(DenyReason.not_in_whitelist, "allow.addresses",
                         "Получатель не в whitelist", version)

    # 6. Лимит на транзакцию
    if value > m.limits.per_tx_eth:
        return _deny(DenyReason.over_per_tx_limit, "limits.per_tx_eth",
                     f"{value} ETH > лимита на транзакцию {m.limits.per_tx_eth}", version)

    # 7. Дневной лимит
    if ctx.spent_today_eth + value > m.limits.daily_eth:
        return _deny(DenyReason.over_daily_limit, "limits.daily_eth",
                     f"Дневной лимит {m.limits.daily_eth} ETH будет превышен", version)

    # 8. Скорость (velocity)
    window_start = ctx.now_utc.timestamp() - m.limits.velocity.window_min * 60
    recent = [t for t in ctx.recent_tx if t.timestamp() >= window_start]
    if len(recent) >= m.limits.velocity.max_tx:
        return _deny(DenyReason.over_velocity, "limits.velocity",
                     f"Более {m.limits.velocity.max_tx} tx за {m.limits.velocity.window_min} мин", version)

    # 9. Slippage
    slippage = ctx.params.get("slippage_bps")
    if slippage is not None and slippage > m.limits.slippage_bps_max:
        return _deny(DenyReason.slippage_exceeded, "limits.slippage_bps_max",
                     f"Slippage {slippage} bps > допустимого {m.limits.slippage_bps_max}", version)

    # 10. Approve-гигиена
    if action == "approve" and m.deny.unlimited_approve:
        amount = ctx.params.get("amount")
        if amount is None:
            return _deny(DenyReason.infinite_approve, "deny.unlimited_approve",
                         "Approve без точной суммы запрещён", version)
        if amount >= MAX_UINT256:
            return _deny(DenyReason.infinite_approve, "deny.unlimited_approve",
                         "Бесконечный approve (2^256-1) запрещён", version)

    approval_reasons: list[str] = []
    approval_rules: list[str] = []
    approval_codes: list[DenyReason] = []

    def require(code: DenyReason, rule: str, msg: str) -> None:
        approval_codes.append(code)
        approval_rules.append(rule)
        approval_reasons.append(msg)

    # 11. Gas-кап → ручное подтверждение
    if ctx.gas_price_gwei > m.limits.gas_gwei_cap:
        require(DenyReason.gas_cap_exceeded, "limits.gas_gwei_cap",
                f"Gas {ctx.gas_price_gwei} gwei > капа {m.limits.gas_gwei_cap}")

    # 12. Временное окно
    if policy.window is not None:
        now_min = ctx.now_utc.hour * 60 + ctx.now_utc.minute
        start, end = policy.window
        if not _window_open(now_min, start, end):
            return _deny(DenyReason.time_window_closed, "windows.active_utc",
                         "Вне разрешённого временного окна", version)

    # 13. Circuit breakers
    if ctx.anomaly_score >= m.circuit_breakers.anomaly_score_gte:
        return _deny(DenyReason.anomaly_detected, "circuit_breakers.anomaly_score_gte",
                     f"Anomaly score {ctx.anomaly_score} ≥ порога", version)
    if ctx.revert_streak >= m.circuit_breakers.revert_streak_gte:
        return _deny(DenyReason.anomaly_detected, "circuit_breakers.revert_streak_gte",
                     f"Серия ревертов {ctx.revert_streak} ≥ порога", version)

    # 14. Обязательные подтверждения
    ri = m.approvals.required_if
    if ctx.risk_score >= ri.risk_score_gte:
        require(DenyReason.anomaly_detected, "approvals.required_if.risk_score_gte",
                f"Risk score {ctx.risk_score} ≥ {ri.risk_score_gte}")
    if ri.amount_eth_gte > 0 and value >= ri.amount_eth_gte:
        require(DenyReason.anomaly_detected, "approvals.required_if.amount_eth_gte",
                f"Сумма {value} ETH ≥ {ri.amount_eth_gte} — нужно подтверждение")
    if ri.new_spender and ctx.new_spender:
        require(DenyReason.anomaly_detected, "approvals.required_if.new_spender",
                "Новый spender — нужно подтверждение")

    if approval_reasons:
        return Verdict(VerdictDecision.REQUIRE_APPROVAL, approval_reasons,
                       approval_rules, approval_codes, version)

    return Verdict(VerdictDecision.ALLOW, ["Все проверки Dharma пройдены"], [], [], version)
