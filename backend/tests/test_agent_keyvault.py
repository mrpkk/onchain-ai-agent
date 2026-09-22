"""Тесты S1-04: ленивая инициализация кошелька из KeyVault + миграция env→vault."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from eth_account import Account

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402
from src.security.keyvault import KeyVault, migrate_env_key_to_vault  # noqa: E402

TEST_KEY = "0x" + "ab" * 32


@pytest.fixture
def vault(tmp_path):
    v = KeyVault("test-master-secret", path=tmp_path / "keys.enc")
    v.put_key("agent_wallet", TEST_KEY)
    return v


def make_agent(vault=None):
    return OnChainAgent(AgentConfig(name="test", chain="sepolia"), vault=vault)


def test_wallet_is_lazy(vault, monkeypatch):
    agent = make_agent(vault)
    monkeypatch.setattr(agent.perception, "get_web3", lambda chain: MagicMock())
    assert agent.wallet is None  # ключ не читается при конструировании
    wallet = agent._ensure_wallet()
    assert wallet is not None
    assert wallet.address == Account.from_key(TEST_KEY).address
    assert agent.executor is not None


def test_executor_created_when_rpc_available(vault, monkeypatch):
    """executor создаётся, как только RPC доступен (повторная попытка)."""
    agent = make_agent(vault)
    monkeypatch.setattr(agent.perception, "get_web3", lambda chain: None)
    agent._ensure_wallet()
    assert agent.wallet is not None and agent.executor is None

    monkeypatch.setattr(agent.perception, "get_web3", lambda chain: MagicMock())
    agent._ensure_wallet()
    assert agent.executor is not None


def test_no_vault_no_wallet():
    agent = make_agent(None)
    assert agent._ensure_wallet() is None
    assert agent.wallet is None


def test_missing_key_no_crash(tmp_path):
    v = KeyVault("test-master-secret", path=tmp_path / "keys.enc")
    agent = make_agent(v)
    assert agent._ensure_wallet() is None
    assert agent.wallet is None


def test_migration_env_to_vault(tmp_path, monkeypatch):
    v = KeyVault("test-master-secret", path=tmp_path / "keys.enc")
    monkeypatch.setenv("AGENT_WALLET_PRIVATE_KEY", TEST_KEY)
    assert migrate_env_key_to_vault(v) is True
    assert v.get_key("agent_wallet") == TEST_KEY
    # переменная окружения не удаляется — решает владелец
    assert "AGENT_WALLET_PRIVATE_KEY" in __import__("os").environ


def test_migration_empty_env_is_false(tmp_path, monkeypatch):
    v = KeyVault("test-master-secret", path=tmp_path / "keys.enc")
    monkeypatch.delenv("AGENT_WALLET_PRIVATE_KEY", raising=False)
    assert migrate_env_key_to_vault(v) is False
    assert v.list_names() == []
