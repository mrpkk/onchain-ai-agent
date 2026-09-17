"""Password hashing — Argon2id (SPEC KARTA S1-02).

Argon2id — primary (time_cost=3, memory_cost=64 MiB, parallelism=4);
bcrypt — fallback для внешних/исторических хешей.
Legacy-формат KARTA v1 (``salt:sha256hex``) поддерживается только для миграции:
при первом успешном логине хеш автоматически перевыпускается в Argon2id.
"""

from __future__ import annotations

import hashlib
import hmac

from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__time_cost=3,
    argon2__memory_cost=65536,
    argon2__parallelism=4,
)


def hash_password(password: str) -> str:
    """Возвращает Argon2id-хеш пароля."""
    return pwd_context.hash(password)


def needs_upgrade(stored: str) -> bool:
    """True, если хеш в legacy-формате v1 (``salt:sha256hex``)."""
    return ":" in stored and not stored.startswith("$")


def _verify_legacy(password: str, stored: str) -> bool:
    """Проверка legacy ``salt:sha256(salt+password)`` (constant-time)."""
    try:
        salt, old_hash = stored.split(":", 1)
    except ValueError:
        return False
    calc = hashlib.sha256((password + salt).encode()).hexdigest()
    return hmac.compare_digest(calc, old_hash)


def verify_password(password: str, stored: str) -> bool:
    """Проверка пароля против Argon2id/bcrypt/legacy-хеша."""
    if needs_upgrade(stored):
        return _verify_legacy(password, stored)
    try:
        return pwd_context.verify(password, stored)
    except ValueError:
        return False


def verify_and_upgrade(password: str, stored: str) -> tuple[bool, str | None]:
    """Проверяет пароль и, при необходимости, возвращает новый Argon2id-хеш.

    Returns:
        (ok, new_hash | None): ``new_hash`` не None, если хеш был legacy
        или требует обновления параметров — вызывающий должен сохранить его.
    """
    if needs_upgrade(stored):
        if _verify_legacy(password, stored):
            return True, hash_password(password)
        return False, None

    try:
        ok = pwd_context.verify(password, stored)
    except ValueError:
        return False, None

    if ok and pwd_context.needs_update(stored):
        return True, hash_password(password)
    return ok, None
