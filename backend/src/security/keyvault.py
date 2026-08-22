"""KeyVault — шифрованное хранение приватных ключей агента (RTM NFR-1).

Угроза: приватник в открытом виде в настройках/атрибутах утекает через
дампы памяти, логи, сериализацию. Решение: ключи хранятся зашифрованными
(Fernet, AES-128-CBC + HMAC), расшифровка — только на момент подписи.

Мастер-ключ: env ONCHAIN_MASTER_KEY (32+ байта, base64 или passphrase).
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

KEYSTORE_FILENAME = "keys.enc"
_SALT = b"onchain-ai-agent-keystore-v1"


def _fernet_from_secret(secret: str) -> Fernet:
    """Fernet из произвольного секрета: PBKDF2 -> 32 байта -> urlsafe-b64."""
    digest = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT,
                        iterations=200_000)
    raw = digest.derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(raw))


def master_key_from_env() -> str:
    key = os.environ.get("ONCHAIN_MASTER_KEY", "")
    if not key:
        raise RuntimeError(
            "ONCHAIN_MASTER_KEY не задан — хранилище ключей недоступно. "
            "Сгенерируйте: openssl rand -hex 32"
        )
    return key


class KeyVault:
    """Зашифрованное keystore-хранилище {name: private_key}."""

    def __init__(self, master_secret: str, path: Path | str | None = None):
        self._fernet = _fernet_from_secret(master_secret)
        self.path = Path(path) if path else (
            Path.home() / ".onchain-agent" / KEYSTORE_FILENAME
        )

    # ── базовые операции ────────────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            blob = self._fernet.decrypt(self.path.read_bytes())
            return json.loads(blob)
        except (InvalidToken, json.JSONDecodeError) as e:
            raise RuntimeError(f"Keystore повреждён или неверный мастер-ключ: {e}")

    def save(self, store: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        blob = self._fernet.encrypt(json.dumps(store).encode())
        # атомарная запись + права только для владельца
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def put_key(self, name: str, private_key: str) -> None:
        store = self.load()
        store[name] = {"private_key": private_key}
        self.save(store)

    def get_key(self, name: str) -> str:
        entry = self.load().get(name)
        if not entry:
            raise KeyError(f"Ключ '{name}' не найден в хранилище")
        return entry["private_key"]

    def delete_key(self, name: str) -> None:
        store = self.load()
        store.pop(name, None)
        self.save(store)

    def list_names(self) -> list[str]:
        return sorted(self.load().keys())

    @staticmethod
    def redact(key: str) -> str:
        """Безопасное представление ключа для логов: 0x1234…abcd."""
        tail = re.sub(r"[^0-9a-fA-F]", "", key)[-4:] or "****"
        return f"***…{tail}"
