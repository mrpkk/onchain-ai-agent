"""Менеджер запущенных runtime-агентов (SPEC S3-06)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Optional

from ..agent.core import OnChainAgent

logger = logging.getLogger("runtime.manager")


class RuntimeManager:
    """In-process реестр запущенных агентов и их asyncio-задач."""

    def __init__(self) -> None:
        self._runtimes: dict[str, OnChainAgent] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self, agent_id: str, agent: OnChainAgent) -> bool:
        if agent_id in self._runtimes:
            return False
        self._runtimes[agent_id] = agent
        self._tasks[agent_id] = asyncio.create_task(agent.start())
        await asyncio.sleep(0)  # даём задаче стартовать детерминированно
        logger.info("Runtime started: %s", agent_id)
        return True

    async def stop(self, agent_id: str) -> bool:
        agent = self._runtimes.pop(agent_id, None)
        task = self._tasks.pop(agent_id, None)
        if agent is None:
            return False
        await agent.stop()
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        logger.info("Runtime stopped: %s", agent_id)
        return True

    def get(self, agent_id: str) -> Optional[OnChainAgent]:
        return self._runtimes.get(agent_id)

    def is_running(self, agent_id: str) -> bool:
        return agent_id in self._runtimes

    @property
    def count(self) -> int:
        return len(self._runtimes)

    def reset(self) -> None:
        """Сброс реестра (для тестов; задачи не отменяет — только забывает)."""
        self._runtimes.clear()
        self._tasks.clear()


manager = RuntimeManager()
