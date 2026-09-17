"""Тесты S1-09: честный health — реальные проверки, без фейковых «ok»."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.api import health as health_module  # noqa: E402


class _Settings:
    database_url = "postgresql+asyncpg://agent:agent@localhost:5432/onchain_ai"
    redis_url = "redis://localhost:6379/0"
    ethereum_rpc_url = "https://eth.llamarpc.com"


def _run(coro):
    return asyncio.run(coro)


def _patch_all(monkeypatch, db, redis_state, rpc, llm="not_configured", vault="not_configured"):
    async def tcp(url, default_port, timeout=1.5):
        return db if default_port == 5432 else redis_state

    async def rpc_check(url, timeout=3.0):
        return {"status": rpc}

    monkeypatch.setattr(health_module, "_tcp_check", tcp)
    monkeypatch.setattr(health_module, "_rpc_check", rpc_check)
    monkeypatch.setattr(health_module, "_llm_status", lambda: {"status": llm})
    monkeypatch.setattr(health_module, "_keyvault_status", lambda: vault)


def test_health_down_when_nothing_reachable(monkeypatch):
    _patch_all(monkeypatch, "down", "down", "down")
    result = _run(health_module.collect_health(_Settings(), 0.0))
    assert result["status"] == "down"
    assert result["components"]["redis"] == "down"  # не «ok»-заглушка
    assert result["components"]["database"] == "down"
    assert result["components"]["rpc"]["status"] == "down"


def test_health_degraded_when_partial(monkeypatch):
    _patch_all(monkeypatch, "ok", "down", "down")
    result = _run(health_module.collect_health(_Settings(), 0.0))
    assert result["status"] == "degraded"
    assert result["components"]["database"] == "ok"


def test_health_ok_when_all_configured(monkeypatch):
    _patch_all(monkeypatch, "ok", "ok", "ok", llm="configured", vault="configured")
    result = _run(health_module.collect_health(_Settings(), 0.0))
    assert result["status"] == "ok"
    assert result["components"]["llm"]["status"] == "configured"


def test_tcp_check_not_configured_on_empty_url():
    assert _run(health_module._tcp_check("", 5432)) == "not_configured"


def test_tcp_check_down_on_refused_port():
    """Реальная проверка (без моков): закрытый порт → down."""
    assert _run(health_module._tcp_check("redis://127.0.0.1:1/0", 6379)) == "down"


def test_main_source_has_no_fake_health_literals():
    """В api/main.py не осталось фейковых литералов health."""
    source = (ROOT / "backend/src/api/main.py").read_text(encoding="utf-8")
    assert "redis_connected=True" not in source
    assert "blockchain_connected=True" not in source
