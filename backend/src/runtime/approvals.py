"""Одобрение решений (SPEC S4-06): единый путь web/Telegram — policy не обходится.

Кнопка «Одобрить» в Telegram вызывает ту же функцию, что и web-API;
исполнение идёт через runtime.execute_intent → полный контур ядра
(policy → simulation → timelock → dispatch).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from ..db import AgentRepository, ApprovalRepository, DecisionRepository, session_scope
from .manager import manager as runtime_manager

logger = logging.getLogger("runtime.approvals")


async def resolve_approval(approval_id: str, action: str, *,
                           actor_user_id: Optional[uuid.UUID] = None,
                           comment: Optional[str] = None,
                           require_owner: Optional[uuid.UUID] = None) -> dict:
    """action: "approve" | "reject". Возвращает {status, executed, detail|error}."""
    try:
        aid = uuid.UUID(approval_id)
    except (ValueError, AttributeError):
        return {"error": "invalid approval id"}

    status = "approved" if action == "approve" else "rejected"
    async with session_scope() as session:
        approvals = ApprovalRepository(session)
        approval = await approvals.get(aid)
        if approval is None:
            return {"error": "approval not found"}
        if approval.status != "pending":
            return {"error": f"approval already {approval.status}"}

        decision = None
        agent = None
        if approval.decision_id is not None:
            decision = await DecisionRepository(session).get(approval.decision_id)
            if decision is not None:
                agent = await AgentRepository(session).get(decision.agent_id)

        if require_owner is not None:
            if agent is None or str(agent.owner_id) != str(require_owner):
                return {"error": "approval not found"}

        await approvals.resolve(aid, status, decided_by=actor_user_id, comment=comment)

        action_name = decision.action if decision else None
        params = dict(decision.params or {}) if decision else {}
        agent_id = str(agent.id) if agent else None

    result: dict = {"status": status, "executed": False,
                    "agent_id": agent_id, "action": action_name}
    if status == "approved" and agent_id and action_name:
        runtime = runtime_manager.get(agent_id)
        if runtime is not None:
            exec_result = await runtime.execute_intent(action_name, params)
            result["executed"] = exec_result.get("status") == "confirmed"
            result["detail"] = exec_result
        else:
            result["detail"] = {"info": "agent is not running; approval recorded"}
    else:
        result["detail"] = {"info": "rejected by user"}
    return result
