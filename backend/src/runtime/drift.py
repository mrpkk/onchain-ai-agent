"""Autonomy Drift Detection (SPEC S4-10/P7): отклонения в поведении агента.

Сравнивает последнее окно решений с предыдущим: средняя сумма, новые типы
действий, рост риск-уровня. Выдаёт только факты и сигналы (без авто-действий).
Честное ограничение: частотный анализ требует зрелой истории — v1 работает
по сумме/миксу/риску.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import DecisionRepository


def _amount(decision) -> float:
    params = decision.params or {}
    value = params.get("amount") or params.get("value") or 0
    return float(value) if isinstance(value, (int, float)) else 0.0


async def detect_drift(session: AsyncSession, agent_id: uuid.UUID,
                       window: int = 20) -> dict:
    decisions = await DecisionRepository(session).list_for_agent(agent_id, limit=window * 2)
    half = min(window, len(decisions) // 2)
    recent = list(decisions[:half])
    previous = list(decisions[half:half * 2])

    signals: list[dict] = []
    if len(recent) >= 5 and len(previous) >= 5:
        avg_recent = sum(_amount(d) for d in recent) / len(recent)
        avg_prev = sum(_amount(d) for d in previous) / len(previous)
        if avg_prev > 0 and avg_recent > avg_prev * 2:
            signals.append({
                "type": "amount_spike",
                "detail": f"средняя сумма ×{avg_recent / avg_prev:.1f} "
                          f"({avg_prev:.4f} → {avg_recent:.4f})",
            })

        mix_recent = {d.action for d in recent}
        mix_prev = {d.action for d in previous}
        new_actions = sorted(mix_recent - mix_prev)
        if new_actions:
            signals.append({"type": "new_actions", "detail": ", ".join(new_actions)})

        high_recent = sum(1 for d in recent if d.risk_level in ("high", "critical"))
        high_prev = sum(1 for d in previous if d.risk_level in ("high", "critical"))
        if high_recent > high_prev + 2:
            signals.append({
                "type": "risk_growth",
                "detail": f"high/critical: {high_prev} → {high_recent}",
            })

    drift_score = min(100, len(signals) * 25)
    level = "stable" if not signals else ("watch" if drift_score <= 25 else "drift")
    return {
        "agent_id": str(agent_id),
        "window": window,
        "analyzed": len(recent) + len(previous),
        "signals": signals,
        "drift_score": drift_score,
        "level": level,
        "note": "v1: сумма/микс действий/риск; частотный анализ — при зрелой истории",
    }
