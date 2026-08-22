"""Тесты KeyVault и защиты ключей (RTM NFR-1) — без сети и блокчейна."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.security.keyvault import KeyVault, _fernet_from_secret  # noqa: E402

TEST_KEY = "0x" + "ab" * 32  # валидный формат приватника для тестов


@pytest.fixture
def vault(tmp_path):
    return KeyVault("correct-horse-battery", path=tmp_path / "keys.enc")


def test_roundtrip_put_get(vault):
    vault.put_key("main", TEST_KEY)
    assert vault.get_key("main") == TEST_KEY
    assert vault.list_names() == ["main"]


def test_wrong_master_fails(tmp_path):
    v1 = KeyVault("secret-one", path=tmp_path / "keys.enc")
    v1.put_key("k", TEST_KEY)
    v2 = KeyVault("secret-two", path=tmp_path / "keys.enc")
    with pytest.raises(RuntimeError, match="повреждён|неверный"):
        v2.get_key("k")


def test_delete_key(vault):
    vault.put_key("a", TEST_KEY)
    vault.delete_key("a")
    assert vault.list_names() == []


def test_keystore_file_is_encrypted(vault):
    vault.put_key("main", TEST_KEY)
    raw = vault.path.read_bytes()
    assert TEST_KEY.encode() not in raw          # ключа нет в открытом виде
    assert b"private_key" not in raw             # и JSON-структуры тоже
    # права только для владельца
    import os
    assert (vault.path.stat().st_mode & 0o077) == 0


def test_redact_hides_material():
    redacted = KeyVault.redact(TEST_KEY)
    assert "ab" * 10 not in redacted
    assert redacted.startswith("***")


def test_wallet_manager_hides_key():
    """WalletManager: атрибут private_key защищён от чтения/сериализации."""
    eth_account = pytest.importorskip("eth_account")
    from src.agent.execution import WalletManager

    wm = WalletManager.__new__(WalletManager)  # без __init__ — не нужен RPC
    wm._key_material = TEST_KEY
    with pytest.raises(AttributeError):
        _ = wm.private_key
    r = repr(wm)
    assert "ab" * 10 not in r
