"""Sakshi Log — append-only аудит с HMAC-цепочкой (SPEC S2-02).

Цепочка: hash_n = HMAC-SHA256(audit_key, prev_hash ‖ canonical(payload)).
Любая правка/подмена строки ломает verify_chain. Ключ: SAKSHI_AUDIT_KEY
(фолбэк ONCHAIN_MASTER_KEY).
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import uuid
from typing import Iterable, Optional, Sequence

import sqlalchemy as sa

from ..db.models import AuditEvent


class AuditKeyMissing(RuntimeError):
    """Ключ аудита не задан — HMAC-цепочка невозможна."""


def audit_key_from_env() -> str:
    key = os.environ.get("SAKSHI_AUDIT_KEY") or os.environ.get("ONCHAIN_MASTER_KEY") or ""
    if not key:
        raise AuditKeyMissing("SAKSHI_AUDIT_KEY (или ONCHAIN_MASTER_KEY) не задан")
    return key


def canonical_payload(payload: dict) -> str:
    """Каноническая JSON-форма (детерминированный порядок ключей)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def compute_hash(audit_key: str, prev_hash: str, payload: dict) -> str:
    message = f"{prev_hash}|{canonical_payload(payload)}".encode()
    return hmac.new(audit_key.encode(), message, hashlib.sha256).hexdigest()


class SakshiLog:
    """Запись, проверка и экспорт аудит-событий (append-only)."""

    def __init__(self, audit_key: Optional[str] = None):
        self._audit_key = audit_key or audit_key_from_env()

    @property
    def audit_key(self) -> str:
        return self._audit_key

    async def append(self, session, *, actor: str, event_type: str, payload: dict,
                     agent_id: Optional[uuid.UUID] = None) -> AuditEvent:
        """Добавляет событие, продолжая HMAC-цепочку. Append-only."""
        prev_hash = await self._last_hash(session)
        event = AuditEvent(
            agent_id=agent_id,
            actor=actor,
            event_type=event_type,
            payload=payload or {},
            prev_hash=prev_hash,
            hash=compute_hash(self._audit_key, prev_hash or "", payload or {}),
        )
        session.add(event)
        await session.flush()
        return event

    async def _last_hash(self, session) -> Optional[str]:
        result = await session.execute(
            sa.select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        return row

    async def list_events(self, session, agent_id: Optional[uuid.UUID] = None,
                          limit: int = 1000) -> Sequence[AuditEvent]:
        stmt = sa.select(AuditEvent).order_by(AuditEvent.id.asc()).limit(limit)
        if agent_id is not None:
            stmt = stmt.where(AuditEvent.agent_id == agent_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    def verify_chain(self, events: Iterable[AuditEvent]) -> bool:
        """True, если цепочка неразрывна и все HMAC совпадают."""
        prev: Optional[str] = None
        for event in sorted(events, key=lambda e: e.id):
            expected = compute_hash(self._audit_key, event.prev_hash or "", event.payload or {})
            if event.prev_hash != prev or event.hash != expected:
                return False
            prev = event.hash
        return True

    @staticmethod
    def export_json(events: Iterable[AuditEvent]) -> str:
        rows = [
            {
                "id": e.id,
                "agent_id": str(e.agent_id) if e.agent_id else None,
                "actor": e.actor,
                "event_type": e.event_type,
                "payload": e.payload,
                "prev_hash": e.prev_hash,
                "hash": e.hash,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in sorted(events, key=lambda x: x.id)
        ]
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @staticmethod
    def export_csv(events: Iterable[AuditEvent]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "agent_id", "actor", "event_type", "payload", "prev_hash", "hash", "created_at"])
        for e in sorted(events, key=lambda x: x.id):
            writer.writerow([
                e.id,
                str(e.agent_id) if e.agent_id else "",
                e.actor,
                e.event_type,
                canonical_payload(e.payload or {}),
                e.prev_hash or "",
                e.hash or "",
                e.created_at.isoformat() if e.created_at else "",
            ])
        return buffer.getvalue()
