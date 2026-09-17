"""Честный health-check (SPEC S1-09): реальные проверки, никаких хардкод-«ok».

Компоненты: database (TCP), redis (TCP), rpc (eth_blockNumber), llm (configured),
keyvault (ONCHAIN_MASTER_KEY). Статусы: ok | degraded | down | not_configured.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from urllib.parse import urlparse

from ..agent.reasoning import GIGACHAT_AUTH_KEY

_OK_STATES = ("ok", "configured")


async def _tcp_check(url: str, default_port: int, timeout: float = 1.5) -> str:
    """TCP-доступность сервиса (Postgres/Redis): ok | down | not_configured."""
    if not url:
        return "not_configured"
    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or default_port
    if not host:
        return "not_configured"

    def _connect() -> bool:
        with socket.create_connection((host, port), timeout=timeout):
            return True

    try:
        await asyncio.wait_for(asyncio.to_thread(_connect), timeout + 0.5)
        return "ok"
    except Exception:
        return "down"


async def _rpc_check(rpc_url: str, timeout: float = 3.0) -> dict:
    """RPC-проверка через eth_blockNumber."""
    if not rpc_url:
        return {"status": "not_configured"}
    from web3 import Web3

    def _probe() -> int:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
        return int(w3.eth.block_number)

    try:
        block = await asyncio.wait_for(asyncio.to_thread(_probe), timeout + 1.0)
        return {"status": "ok", "block_number": block}
    except Exception as e:
        return {"status": "down", "error": type(e).__name__}


def _llm_status() -> dict:
    if GIGACHAT_AUTH_KEY:
        return {"status": "configured", "primary": "gigachat"}
    if os.getenv("DEEPSEEK_API_KEY_0") or os.getenv("DEEPSEEK_API_KEY"):
        return {"status": "configured", "primary": "deepseek"}
    if os.getenv("MISTRAL_API_KEY"):
        return {"status": "configured", "primary": "mistral-legacy"}
    return {"status": "not_configured"}


def _keyvault_status() -> str:
    return "configured" if os.getenv("ONCHAIN_MASTER_KEY") else "not_configured"


async def collect_health(settings, started_at: float) -> dict:
    """Реальный статус всех компонентов: ok/degraded/down (без фейков)."""
    database, redis_state, rpc = await asyncio.gather(
        _tcp_check(settings.database_url, 5432),
        _tcp_check(settings.redis_url, 6379),
        _rpc_check(settings.ethereum_rpc_url),
    )
    components = {
        "database": database,
        "redis": redis_state,
        "rpc": rpc,
        "llm": _llm_status(),
        "keyvault": _keyvault_status(),
    }
    states = [v if isinstance(v, str) else v["status"] for v in components.values()]
    if all(s in _OK_STATES for s in states):
        status = "ok"
    elif any(s in _OK_STATES for s in states):
        status = "degraded"
    else:
        status = "down"
    return {
        "status": status,
        "uptime": round(time.time() - started_at, 2),
        "components": components,
    }
