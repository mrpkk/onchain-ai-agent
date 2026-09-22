"""Timelock / undo-window для необратимых действий (SPEC S3-03).

Действия с суммой ≥ threshold и включённым окном не исполняются сразу:
они попадают в очередь с `execute_after`, откуда их можно отменить
(или дождаться — `_process_due_actions` в тике исполнит их заново
через полный контур policy → simulation).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PendingAction:
    id: str
    action: str
    params: dict
    created_at: datetime
    execute_after: datetime
    status: str = "pending"  # pending|cancelled|executed|failed

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "params": self.params,
            "created_at": self.created_at.isoformat(),
            "execute_after": self.execute_after.isoformat(),
            "status": self.status,
        }


class TimelockQueue:
    """Очередь отложенных действий с окном отмены."""

    def __init__(self) -> None:
        self._items: dict[str, PendingAction] = {}

    def schedule(self, action: str, params: dict, window_seconds: float,
                 now: Optional[datetime] = None) -> PendingAction:
        now = now or _now()
        item = PendingAction(
            id=uuid.uuid4().hex[:12],
            action=action,
            params=dict(params or {}),
            created_at=now,
            execute_after=now + timedelta(seconds=window_seconds),
        )
        self._items[item.id] = item
        return item

    def cancel(self, item_id: str) -> bool:
        item = self._items.get(item_id)
        if item is None or item.status != "pending":
            return False
        item.status = "cancelled"
        return True

    def mark(self, item_id: str, status: str) -> None:
        item = self._items.get(item_id)
        if item is not None:
            item.status = status

    def pending(self) -> list[PendingAction]:
        return [i for i in self._items.values() if i.status == "pending"]

    def due(self, now: Optional[datetime] = None) -> list[PendingAction]:
        now = now or _now()
        return [i for i in self.pending() if i.execute_after <= now]

    def get(self, item_id: str) -> Optional[PendingAction]:
        return self._items.get(item_id)
