"""Decision Replay v1 (SPEC S4-10/P7): переигрывание решения.

Восстанавливает сохранённое решение: что было решено, какой был policy_verdict
тогда и какой вердикт даёт ТЕКУЩАЯ политика сейчас. Симуляция/исполнение
не запускаются (Phase 5) — это честная policy-переоценка.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AgentRepository, DecisionRepository, PolicyRepository
from ..security.dharma import TxContext, build_default_policy, compile_yaml, evaluate


async def replay_decision(session: AsyncSession, decision_id: uuid.UUID) -> Optional[dict]:
    decision = await DecisionRepository(session).get(decision_id)
    if decision is None:
        return None
    agent = await AgentRepository(session).get(decision.agent_id)
    policy_row = await PolicyRepository(session).get_active(decision.agent_id)
    current = compile_yaml(policy_row.dsl_yaml) if policy_row else build_default_policy()

    ctx = TxContext(
        action=decision.action, params=decision.params or {},
        chain_id=agent.chain_id if agent else None,
        gas_price_gwei=0.0, risk_score=decision.risk_score or 0.0,
    )
    now_verdict = evaluate(current, ctx).to_dict()
    then_verdict = decision.policy_verdict or None
    changed = bool(then_verdict) and then_verdict.get("decision") != now_verdict["decision"]

    return {
        "decision": {
            "id": str(decision.id),
            "agent_id": str(decision.agent_id),
            "action": decision.action,
            "params": decision.params or {},
            "reasoning": decision.reasoning,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
            "status": decision.status,
            "created_at": decision.created_at.isoformat() if decision.created_at else None,
        },
        "then": then_verdict,
        "now": now_verdict,
        "verdict_changed": changed,
        "note": "replay v1: policy-переоценка; симуляция/исполнение — Phase 5",
    }
