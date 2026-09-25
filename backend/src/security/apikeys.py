"""API-ключи KARTA (`karta_`): выпуск, хэширование, проверка (S6-04).

Плейн-ключ показывается владельцу ОДИН раз (при выпуске); в БД — только SHA-256.
Ключ привязан к owner: каждый MCP-tool работает в скоупе владельца ключа
(OWASP MCP: confused deputy — session isolation через ключ, а не общий контекст).
"""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "karta_"
ALLOWED_SCOPES = ("mcp:read", "mcp:write")


def hash_api_key(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Возвращает (plain, sha256_hex, display_prefix). Plain существует только здесь."""
    plain = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return plain, hash_api_key(plain), plain[:12]


def is_api_key(token: str) -> bool:
    return token.startswith(KEY_PREFIX)
