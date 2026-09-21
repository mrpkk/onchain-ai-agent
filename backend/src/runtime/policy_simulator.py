"""Policy Simulator (SPEC S4-10/P7): влияние политики на последние решения.

Ничего не применяет: прогоняет историю решений через текущую и кандидатную
политики и показывает, какие вердикты изменились (ужесточение/ослабление).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import DecisionRepository, PolicyRepository
from ..security.dharma import TxContext, build_default_policy, compile_yaml, evaluate

_ORDER = {"deny": 0, "require_approval": 1, "allow": 2}


async def simulate_policy_change(session: AsyncSession, agent_id: uuid.UUID,
                                 candidate_dsl: str, *,
                                 chain_id: int | None = None,
                                 limit: int = 50) -> dict:
    current_row = await PolicyRepository(session).get_active(agent_id)
    current = compile_yaml(current_row.dsl_yaml) if current_row else build_default_policy()
    candidate = compile_yaml(candidate_dsl)

    decisions = await DecisionRepository(session).list_for_agent(agent_id, limit=limit)

    changes: list[dict] = []
    summary = {"tightened": 0, "relaxed": 0, "unchanged": 0}
    for decision in decisions:
        ctx = TxContext(
            action=decision.action, params=decision.params or {},
            chain_id=chain_id, gas_price_gwei=0.0,
            risk_score=decision.risk_score or 0.0, new_spender=False,
        )
        before = evaluate(current, ctx).to_dict()["decision"]
        after = evaluate(candidate, ctx).to_dict()["decision"]
        if before == after:
            summary["unchanged"] += 1
            continue
        direction = "relaxed" if _ORDER.get(after, 1) > _ORDER.get(before, 1) else "tightened"
        summary[direction] += 1
        changes.append({
            "decision_id": str(decision.id),
            "action": decision.action,
            "before": before,
            "after": after,
            "direction": direction,
        })

    return {
        "decisions_analyzed": len(decisions),
        "changes": changes,
        "summary": summary,
        "applied": False,
        "note": "предварительная оценка: газ/история не учтены; политика НЕ применена",
    }
