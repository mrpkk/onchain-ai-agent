"""JWT access/refresh с ротацией и reuse-detection (SPEC S1-03).

Access: 15 мин, type=access. Refresh: 7 дней, type=refresh, family_id.
Ротация: каждый refresh заменяет предыдущий (revoked + replaced_by).
Reuse-detection: повторное использование ротированного refresh → отзыв всей семьи.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

ACCESS = "access"
REFRESH = "refresh"


class TokenError(Exception):
    """Ошибка токена: код + сообщение (машинно-читаемо)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(sub: str, secret: str, algorithm: str = "HS256",
                 token_type: str = ACCESS,
                 expires_delta: timedelta | None = None,
                 family_id: str | None = None,
                 jti: str | None = None) -> str:
    """Создаёт подписанный JWT с типом, jti и (для refresh) family_id."""
    now = _now()
    payload: dict = {
        "sub": sub,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": now + (expires_delta or timedelta(minutes=15)),
        "jti": jti or uuid.uuid4().hex,
    }
    if token_type == REFRESH:
        payload["family_id"] = family_id or uuid.uuid4().hex
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_token(token: str, secret: str, algorithm: str = "HS256",
                 expected_type: str = ACCESS) -> dict:
    """Декодирует и проверяет токен (подпись, срок, тип). Raises TokenError."""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except JWTError as e:
        raise TokenError("TOKEN_INVALID", f"Invalid token: {e}") from e
    if payload.get("type") != expected_type:
        raise TokenError("TOKEN_WRONG_TYPE", f"Expected {expected_type} token")
    if not payload.get("sub"):
        raise TokenError("TOKEN_INVALID", "Missing subject")
    return payload


@dataclass
class RefreshRecord:
    jti: str
    family_id: str
    sub: str
    expires_at: datetime
    revoked: bool = False
    replaced_by: Optional[str] = None


class RefreshStore:
    """In-memory хранилище refresh-токенов (PG-персистентность — P2/S2-01)."""

    def __init__(self) -> None:
        self._records: dict[str, RefreshRecord] = {}

    def add(self, jti: str, family_id: str, sub: str, expires_at: datetime) -> None:
        self._records[jti] = RefreshRecord(
            jti=jti, family_id=family_id, sub=sub, expires_at=expires_at,
        )

    def get(self, jti: str) -> Optional[RefreshRecord]:
        return self._records.get(jti)

    def rotate(self, jti: str, new_jti: str) -> None:
        """Помечает использованный refresh как ротированный (reuse → revoked)."""
        record = self._records.get(jti)
        if record:
            record.revoked = True
            record.replaced_by = new_jti

    def revoke_family(self, family_id: str) -> int:
        count = 0
        for record in self._records.values():
            if record.family_id == family_id and not record.revoked:
                record.revoked = True
                count += 1
        return count

    def revoke_all_for_user(self, sub: str) -> int:
        count = 0
        for record in self._records.values():
            if record.sub == sub and not record.revoked:
                record.revoked = True
                count += 1
        return count

    def is_active(self, jti: str) -> bool:
        record = self._records.get(jti)
        return bool(record and not record.revoked and record.expires_at > _now())
