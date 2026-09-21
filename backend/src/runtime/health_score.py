"""Agent Health Score (SPEC S4-10): здоровье агента по реальным данным.

Компоненты честные: policy-отказы, провальные/отклонённые решения, доля
провальных транзакций. Рекомендация при critical — только совет (снижение
тира — действие владельца, не автомат).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import DecisionRepository, TransactionRepository


async def compute_health_score(session: AsyncSession, agent_id: uuid.UUID) -> dict:
    decisions = await DecisionRepository(session).list_for_agent(agent_id, limit=200)
    txs = await TransactionRepository(session).list_for_agent(agent_id, limit=200)

    total_decisions = len(decisions)
    policy_denials = sum(
        1 for d in decisions if (d.policy_verdict or {}).get("decision") == "deny"
    )
    failed_decisions = sum(1 for d in decisions if d.status in ("failed", "rejected"))
    pending_approvals = sum(1 for d in decisions if d.requires_approval
                            and d.status == "proposed")
    tx_total = len(txs)
    tx_failed = sum(1 for t in txs if t.status in ("failed", "reverted"))

    penalty = 0
    penalty += min(40, policy_denials * 5)
    penalty += min(30, failed_decisions * 5)
    if tx_total:
        penalty += min(30, int(30 * tx_failed / tx_total))

    score = max(0, 100 - penalty)
    band = "healthy" if score >= 80 else "degraded" if score >= 50 else "critical"

    recommendation = None
    if band == "critical":
        recommendation = "Рекомендуется снизить тир автономии и проверить политику"
    elif band == "degraded":
        recommendation = "Проверьте отклонённые/провальные решения"

    return {
        "agent_id": str(agent_id),
        "score": score,
        "band": band,
        "components": {
            "decisions_total": total_decisions,
            "policy_denials": policy_denials,
            "failed_decisions": failed_decisions,
            "pending_approvals": pending_approvals,
            "transactions_total": tx_total,
            "transactions_failed": tx_failed,
        },
        "recommendation": recommendation,
    }
