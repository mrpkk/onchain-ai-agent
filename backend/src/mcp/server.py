"""KARTA MCP-сервер (S6-04): read-only tools поверх Decision Diary / Sakshi / RPC.

Транспорт: streamable HTTP (stateless) — монтируется в FastAPI на `POST /mcp`.
Auth: `Authorization: Bearer karta_…` (API-ключ владельца; см. /api/v1/api-keys).

OWASP MCP:
- tool-poisoning → определения pinned в contracts.py + parity-тест;
- prompt-injection → tools НЕ ходят по адресам/URL из аргументов (только БД/RPC по своим агентам);
- excessive agency → write-tools в v1 не зарегистрированы (тест);
- confused deputy → каждый вызов аутентифицируется ключом, данные — строго скоуп владельца;
- credential leakage → секреты не логируются, ошибки структурированы.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ..config.settings import get_settings
from ..db import (
    AgentRepository,
    ApiKeyRepository,
    DecisionRepository,
    TransactionRepository,
    session_scope,
)
from ..runtime.drift import detect_drift
from ..runtime.health_score import compute_health_score
from ..runtime.replay import replay_decision
from ..runtime.reports import build_summary
from ..security.apikeys import hash_api_key, is_api_key
from ..security.sakshi import AuditKeyMissing, SakshiLog

logger = logging.getLogger("mcp")

mcp = MCPServer(
    "karta",
    version="0.1.0",
    instructions=(
        "KARTA — read-only MCP для доверенной автономии: агенты, кошельки/балансы, "
        "решения (Decision Diary), аудит (Sakshi), health/trust/дрейф. "
        "Данные строго в скоупе владельца API-ключа. Write-tools gated (не зарегистрированы)."
    ),
)

CHAIN_RPC = {
    1: "https://ethereum-rpc.publicnode.com",
    11155111: "https://ethereum-sepolia-rpc.publicnode.com",
}


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _ok(data: Any, source: str, **extra: Any) -> str:
    meta = {
        "source": source,
        "freshness": "on_request",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta.update(extra)
    return _dumps({"data": data, "meta": meta})


def _err(code: str, message: str, hint: Optional[str] = None) -> str:
    return _dumps({"error": {"code": code, "message": message, "hint": hint}})


def _header(ctx: Context, name: str) -> str:
    headers = getattr(ctx, "headers", None) or {}
    try:
        value = headers.get(name) or headers.get(name.title()) or headers.get(name.capitalize())
    except Exception:  # noqa: BLE001 — заголовки разных типов (dict/Headers)
        value = None
    return (value or "").strip()


async def _auth(ctx: Context) -> tuple[Optional[uuid.UUID], Optional[str]]:
    """Возвращает (owner_id, None) или (None, error-json)."""
    raw = _header(ctx, "authorization")
    token = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
    if not token or not is_api_key(token):
        return None, _err(
            "UNAUTHORIZED",
            "Требуется API-ключ: Authorization: Bearer karta_…",
            "Выпустите ключ: POST /api/v1/api-keys (scope mcp:read)",
        )
    async with session_scope() as session:
        repo = ApiKeyRepository(session)
        key = await repo.find_active_by_hash(hash_api_key(token))
        if key is None:
            return None, _err("UNAUTHORIZED", "Ключ не найден или отозван")
        await repo.touch(key)
        return key.user_id, None


async def _owned_agent(session, agent_id: str, owner_id: uuid.UUID):
    try:
        aid = uuid.UUID(str(agent_id))
    except (ValueError, AttributeError):
        return None
    agent = await AgentRepository(session).get(aid)
    if agent is None or agent.owner_id != owner_id:
        return None
    return agent


async def _rpc_call(rpc_url: str, fn):
    def _probe():
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8.0}))
        return fn(w3)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_probe), 10.0), None
    except Exception as e:  # noqa: BLE001 — честная ошибка наружу
        return None, type(e).__name__


# ── READ tools ──────────────────────────────────────────────────────────

@mcp.tool(name="get_wallet", description="Адрес кошелька, сеть, статус и тир агента (только свои агенты).")
async def tool_get_wallet(agent_id: str, ctx: Context) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        return _ok(
            {
                "agent_id": str(agent.id),
                "name": agent.name,
                "wallet_address": agent.wallet_address,
                "chain_id": agent.chain_id,
                "status": agent.status,
                "tier": agent.tier,
            },
            "postgres:agents",
        )


@mcp.tool(name="get_balance", description="Нативный баланс кошелька агента из реального RPC (ETH).")
async def tool_get_balance(agent_id: str, ctx: Context) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        if not agent.wallet_address:
            return _err("NO_WALLET", "У агента не задан wallet_address")
        rpc_url = CHAIN_RPC.get(agent.chain_id)
        if rpc_url is None:
            return _err("CHAIN_UNSUPPORTED", f"Сеть {agent.chain_id} не подключена (v1: 1, 11155111)")
        address, chain_id = agent.wallet_address, agent.chain_id
    result, rpc_error = await _rpc_call(
        rpc_url,
        lambda w3: {
            "balance": w3.eth.get_balance(w3.to_checksum_address(address)),
            "block": int(w3.eth.block_number),
        },
    )
    if rpc_error:
        return _err("RPC_UNAVAILABLE", f"RPC недоступен: {rpc_error}")
    return _ok(
        {
            "agent_id": str(agent_id),
            "address": address,
            "chain_id": chain_id,
            "balance_eth": float(result["balance"]) / 1e18,
            "block_number": result["block"],
        },
        "rpc:ethereum",
        block=result["block"],
    )


@mcp.tool(name="get_gas", description="Текущая цена газа сети агента (EIP-1559 base/priority) из RPC.")
async def tool_get_gas(agent_id: str, ctx: Context) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        chain_id = agent.chain_id
    rpc_url = CHAIN_RPC.get(chain_id)
    if rpc_url is None:
        return _err("CHAIN_UNSUPPORTED", f"Сеть {chain_id} не подключена (v1: 1, 11155111)")
    result, rpc_error = await _rpc_call(
        rpc_url,
        lambda w3: {
            "block": int(w3.eth.block_number),
            "base_fee": int(getattr(w3.eth.get_block("latest"), "baseFeePerGas", 0) or 0),
            "gas_price": int(w3.eth.gas_price),
        },
    )
    if rpc_error:
        return _err("RPC_UNAVAILABLE", f"RPC недоступен: {rpc_error}")
    base, gp = result["base_fee"], result["gas_price"]
    priority = max(gp - base, 0)
    gwei = 1e9
    return _ok(
        {
            "chain_id": chain_id,
            "base_fee_gwei": round(base / gwei, 3),
            "priority_fee_gwei": round(priority / gwei, 3),
            "gas_price_gwei": round(gp / gwei, 3),
            "block_number": result["block"],
        },
        "rpc:ethereum",
        block=result["block"],
    )


@mcp.tool(name="get_portfolio", description="Честная v1-сводка: нативный баланс + сеть; токены — Phase 5.")
async def tool_get_portfolio(agent_id: str, ctx: Context) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        if not agent.wallet_address:
            return _err("NO_WALLET", "У агента не задан wallet_address")
        address, chain_id = agent.wallet_address, agent.chain_id
    rpc_url = CHAIN_RPC.get(chain_id)
    balance = None
    if rpc_url is not None:
        result, rpc_error = await _rpc_call(
            rpc_url,
            lambda w3: w3.eth.get_balance(w3.to_checksum_address(address)),
        )
        if rpc_error is None:
            balance = float(result) / 1e18
    return _ok(
        {
            "agent_id": str(agent_id),
            "chain_id": chain_id,
            "native_balance_eth": balance,
            "tokens": None,
            "note": "Агрегация ERC-20 — Phase 5; не выдумываем данные",
        },
        "rpc + postgres:agents",
    )


@mcp.tool(name="get_transactions", description="История транзакций агента (Decision→Execution) из БД.")
async def tool_get_transactions(agent_id: str, ctx: Context, limit: int = 20) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    limit = max(1, min(int(limit), 100))
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        repo = TransactionRepository(session)
        rows = await repo.list_for_agent(agent.id, limit=limit)
        total = await repo.count_for_agent(agent.id)
        items = [
            {
                "id": str(tx.id),
                "status": tx.status,
                "tx_hash": tx.tx_hash,
                "action": tx.action,
                "value": (tx.params or {}).get("amount"),
                "gas_used": tx.gas_used,
                "gas_price_gwei": tx.gas_price_gwei,
                "simulated": tx.simulated,
                "created_at": getattr(tx, "created_at", None),
            }
            for tx in rows
        ]
    return _ok({"items": items, "total": total}, "postgres:transactions")


@mcp.tool(name="agent_status", description="Статус, тир, health score, trust-ступень и дрейф агента.")
async def tool_agent_status(agent_id: str, ctx: Context) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        summary = await build_summary(session, agent.id)
        health = await compute_health_score(session, agent.id)
        summary["health"] = health
        drift = await detect_drift(session, agent.id)
        from ..runtime import manager as runtime_manager

        return _ok(
            {
                "agent_id": str(agent.id),
                "status": agent.status,
                "tier": agent.tier,
                "simulation_mode": bool((agent.config or {}).get("simulation_mode", agent.tier <= 1)),
                "running": runtime_manager.is_running(str(agent.id)),
                "health": health,
                "trust": summary.get("trust"),
                "drift": drift,
            },
            "postgres + runtime",
        )


@mcp.tool(name="audit_log", description="Append-only события Sakshi-аудита агента с HMAC-цепочкой.")
async def tool_audit_log(agent_id: str, ctx: Context, limit: int = 50) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    limit = max(1, min(int(limit), 200))
    async with session_scope() as session:
        agent = await _owned_agent(session, agent_id, owner)
        if agent is None:
            return _err("NOT_FOUND", "Агент не найден")
        try:
            log = SakshiLog()
        except AuditKeyMissing:
            return _err("AUDIT_KEY_MISSING", "Аудит-ключ не настроен на сервере")
        events = await log.list_events(session, agent_id=agent.id, limit=limit)
        items = [
            {
                "id": e.id,
                "actor": e.actor,
                "event_type": e.event_type,
                "payload": e.payload or {},
                "prev_hash": e.prev_hash,
                "hash": e.hash,
                "created_at": e.created_at,
            }
            for e in events
        ]
    return _ok({"items": items, "total": len(items)}, "postgres:audit_events")


@mcp.tool(name="get_decision", description="Решение из Decision Diary + вердикт по ТЕКУЩЕЙ политике (replay).")
async def tool_get_decision(decision_id: str, ctx: Context) -> str:
    owner, error = await _auth(ctx)
    if error:
        return error
    try:
        did = uuid.UUID(str(decision_id))
    except (ValueError, AttributeError):
        return _err("NOT_FOUND", "Решение не найдено")
    async with session_scope() as session:
        decision = await DecisionRepository(session).get(did)
        if decision is None:
            return _err("NOT_FOUND", "Решение не найдено")
        agent = await AgentRepository(session).get(decision.agent_id)
        if agent is None or agent.owner_id != owner:
            return _err("NOT_FOUND", "Решение не найдено")
        replay = await replay_decision(session, did)
    return _ok(replay, "postgres:decisions + Dharma")


class MCPDispatcher:
    """Тонкий ASGI-диспетчер mount-точки /mcp.

    Session manager MCP можно запускать только ОДИН раз на инстанс, поэтому
    на каждый lifespan создаётся свежий app; диспетчер остаётся стабильной
    ASGI-точкой для mount в FastAPI (и корректно переживает рестарты в тестах).
    """

    def __init__(self) -> None:
        self._app = None

    @asynccontextmanager
    async def lifespan(self):
        hosts = get_settings().mcp_allowed_hosts
        app = mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
            ),
        )
        self._app = app
        try:
            async with app.router.lifespan_context(app):
                yield
        finally:
            self._app = None

    async def __call__(self, scope, receive, send):
        app = self._app
        if app is None:
            raise RuntimeError("MCP app is not running (lifespan не активен)")
        # Mount срезает префикс: /mcp → path "", /mcp/ → path "/".
        # Внутренний route — "/": нормализуем, чтобы не было redirect 307.
        scope = dict(scope)
        scope["path"] = "/"
        await app(scope, receive, send)


mcp_dispatcher = MCPDispatcher()
