"""S4-17: реконсиляция статусов агентов при старте процесса.

In-process dead-man switch не видит смерть самого процесса (S3-04, долг):
агент, бывший `running` в момент падения/рестарта API, остаётся `running`
в БД, хотя исполнения нет (RuntimeManager — in-memory реестр). Это нечестное
состояние: UI показывает «работает», хотя никто не работает.

Правило: при старте такие агенты переводятся в `stopped` (жёстко, без
автовозобновления — повторный запуск только осознанным действием владельца).
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from ..api.models import AgentStatus
from ..db.database import session_scope
from ..db.models import Agent

logger = logging.getLogger("runtime.reconciliation")

STALE_STATUSES = (AgentStatus.RUNNING.value,)


async def reconcile_stale_agents(session) -> int:
    """Переводит «висящие» running-агенты в stopped. Возвращает число исправленных."""
    rows = await session.execute(select(Agent).where(Agent.status.in_(STALE_STATUSES)))
    stale = list(rows.scalars().all())
    for agent in stale:
        agent.status = AgentStatus.STOPPED.value
    if stale:
        logger.warning(
            "Реконсиляция: %d агент(ов) %s→%s (процесс был остановлен): %s",
            len(stale),
            "/".join(STALE_STATUSES),
            AgentStatus.STOPPED.value,
            ", ".join(str(a.id) for a in stale),
        )
    return len(stale)


async def reconcile_on_startup() -> int:
    """Обёртка для lifespan: своя сессия, честный лог. Не роняет старт."""
    async with session_scope() as session:
        return await reconcile_stale_agents(session)
