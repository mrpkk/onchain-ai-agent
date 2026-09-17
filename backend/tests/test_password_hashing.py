"""Тесты Argon2id-хэширования паролей и миграции legacy-хешей (SPEC S1-02)."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.security.passwords import (  # noqa: E402
    hash_password,
    needs_upgrade,
    verify_and_upgrade,
    verify_password,
)


def test_hash_is_argon2id():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")


def test_roundtrip():
    h = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", h) is True
    assert verify_password("wrong-pass", h) is False


def test_unique_salts():
    assert hash_password("same-password") != hash_password("same-password")


def test_needs_upgrade_detection():
    legacy = "a1b2c3:" + "0" * 64
    assert needs_upgrade(legacy) is True
    assert needs_upgrade(hash_password("x")) is False


def test_legacy_verify_and_upgrade_success():
    salt = "deadbeef"
    legacy = f"{salt}:{hashlib.sha256(('legacy-pass' + salt).encode()).hexdigest()}"
    ok, new_hash = verify_and_upgrade("legacy-pass", legacy)
    assert ok is True
    assert new_hash is not None and new_hash.startswith("$argon2id$")
    # новый хеш валиден для того же пароля
    assert verify_password("legacy-pass", new_hash) is True


def test_legacy_verify_and_upgrade_wrong_password():
    salt = "deadbeef"
    legacy = f"{salt}:{hashlib.sha256(('legacy-pass' + salt).encode()).hexdigest()}"
    ok, new_hash = verify_and_upgrade("wrong-pass", legacy)
    assert ok is False
    assert new_hash is None


def test_argon2_no_upgrade_needed():
    h = hash_password("fresh")
    ok, new_hash = verify_and_upgrade("fresh", h)
    assert ok is True
    assert new_hash is None


def test_malformed_hash_is_rejected_safely():
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("x", "no-colon-just-garbage") is False
