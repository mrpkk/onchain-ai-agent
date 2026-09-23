"""Канон-контракты MCP-tools KARTA (SPEC §10, S6-04).

Поля каждого контракта (обязательны по SPEC): стабильное имя, описание/схема
(схема — из сигнатуры функции, SDK генерирует JSON Schema), units/limits,
error-коды, source/freshness, cost class, rate limit, read/write, risk level.
Для write — idempotency-key (в v1 write-tools не зарегистрированы — gated).

OWASP MCP: этот файл — «pinned definitions» (tool-poisoning): описания и
контракты фиксированы в коде и покрыты parity-тестом.
"""

from __future__ import annotations

READ_TOOLS: dict[str, dict] = {
    "get_wallet": {
        "title": "Кошелёк агента",
        "description": "Адрес кошелька, сеть, статус и тир агента (только свои агенты).",
        "params": "agent_id: str (UUID агента владельца ключа)",
        "returns": "{agent_id, name, wallet_address, chain_id, status, tier}",
        "read_only": True,
        "risk": "low",
        "units": "адрес 0x…, chain_id — EIP-155",
        "limits": "—",
        "source": "postgres:agents",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "60/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND"],
    },
    "get_balance": {
        "title": "Баланс агента",
        "description": "Нативный баланс кошелька агента из реального RPC (ETH).",
        "params": "agent_id: str",
        "returns": "{agent_id, address, chain_id, balance_eth, block_number}",
        "read_only": True,
        "risk": "low",
        "units": "ETH (wei → ETH)",
        "limits": "—",
        "source": "rpc:ethereum (PublicNode)",
        "freshness": "on_request (блок сети)",
        "cost_class": "free",
        "rate_limit": "30/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND", "NO_WALLET", "CHAIN_UNSUPPORTED", "RPC_UNAVAILABLE"],
    },
    "get_gas": {
        "title": "Газ (EIP-1559)",
        "description": "Текущая цена газа сети агента (base fee + priority) из RPC.",
        "params": "agent_id: str",
        "returns": "{chain_id, base_fee_gwei, priority_fee_gwei, gas_price_gwei, block_number}",
        "read_only": True,
        "risk": "low",
        "units": "gwei",
        "limits": "—",
        "source": "rpc:ethereum (PublicNode)",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "30/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND", "CHAIN_UNSUPPORTED", "RPC_UNAVAILABLE"],
    },
    "get_portfolio": {
        "title": "Портфель агента",
        "description": "Честная v1-сводка: нативный баланс + сеть; агрегация токенов — Phase 5 (не выдумываем).",
        "params": "agent_id: str",
        "returns": "{agent_id, chain_id, native_balance_eth, tokens: null, note}",
        "read_only": True,
        "risk": "low",
        "units": "ETH",
        "limits": "—",
        "source": "rpc + postgres:agents",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "30/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND", "NO_WALLET", "RPC_UNAVAILABLE"],
    },
    "get_transactions": {
        "title": "Транзакции агента",
        "description": "История транзакций агента (Decision→Execution) из БД.",
        "params": "agent_id: str, limit: int = 20 (1..100)",
        "returns": "{items: [{id, status, tx_hash, value_eth, gas_used, created_at}], total}",
        "read_only": True,
        "risk": "low",
        "units": "ETH, wei",
        "limits": "limit ≤ 100",
        "source": "postgres:transactions",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "60/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND"],
    },
    "agent_status": {
        "title": "Статус и здоровье агента",
        "description": "Статус, тир, режим симуляции, health score, trust-ступень, дрейф.",
        "params": "agent_id: str",
        "returns": "{status, tier, simulation_mode, running, health, trust, drift}",
        "read_only": True,
        "risk": "low",
        "units": "score 0–100",
        "limits": "—",
        "source": "postgres + runtime",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "60/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND"],
    },
    "audit_log": {
        "title": "Sakshi-аудит агента",
        "description": "Append-only события аудита агента с HMAC-цепочкой (hash/prev_hash).",
        "params": "agent_id: str, limit: int = 50 (1..200)",
        "returns": "{items: [{id, actor, event_type, payload, prev_hash, hash, created_at}], total}",
        "read_only": True,
        "risk": "low",
        "units": "—",
        "limits": "limit ≤ 200",
        "source": "postgres:audit_events (HMAC)",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "30/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND", "AUDIT_KEY_MISSING"],
    },
    "get_decision": {
        "title": "Решение + Replay",
        "description": "Решение из Decision Diary и его вердикт по ТЕКУЩЕЙ политике (replay).",
        "params": "decision_id: str (UUID решения владельца ключа)",
        "returns": "{decision, then, now, verdict_changed}",
        "read_only": True,
        "risk": "low",
        "units": "—",
        "limits": "—",
        "source": "postgres:decisions + Dharma",
        "freshness": "on_request",
        "cost_class": "free",
        "rate_limit": "60/min/key",
        "errors": ["UNAUTHORIZED", "NOT_FOUND"],
    },
}

# Целевые write-tools SPEC §10 — НЕ зарегистрированы в v1 (gated: scope mcp:write + решение владельца).
WRITE_TOOLS_GATED: dict[str, dict] = {
    "simulate_transaction": {"read_only": False, "risk": "low", "status": "gated (v1 не зарегистрирован)"},
    "create_plan": {"read_only": False, "risk": "medium", "status": "gated"},
    "request_approval": {"read_only": False, "risk": "medium", "status": "gated"},
    "execute_transaction": {"read_only": False, "risk": "high", "status": "gated (STOP-GATE: реальное исполнение)"},
    "agent_pause": {"read_only": False, "risk": "medium", "status": "gated"},
    "agent_kill": {"read_only": False, "risk": "high", "status": "gated"},
}


def tool_contracts_markdown() -> str:
    """Markdown-документ контрактов (генерируется в docs/MCP_TOOL_CONTRACTS.md)."""
    lines = [
        "# KARTA MCP — контракты tools",
        "",
        "> AUTO-GENERATED: `docs/generate_mcp_contracts.py` (источник — `backend/src/mcp/contracts.py`).",
        "> Транспорт: **streamable HTTP (stateless)**, `POST /mcp`, auth: `Authorization: Bearer karta_…`.",
        "> Все ошибки — структурированные: `{\"error\": {\"code\", \"message\", \"hint\"}}`.",
        "",
        "## READ (зарегистрированы в v1)",
        "",
    ]
    for name, c in READ_TOOLS.items():
        lines += [
            f"### `{name}` — {c['title']}",
            "",
            f"- **Описание:** {c['description']}",
            f"- **Параметры:** `{c['params']}`",
            f"- **Возврат:** `{c['returns']}`",
            f"- **read/write:** read-only · **risk:** {c['risk']} · **cost:** {c['cost_class']}",
            f"- **Units/limits:** {c['units']} · {c['limits']}",
            f"- **Source/freshness:** {c['source']} · {c['freshness']}",
            f"- **Rate limit:** {c['rate_limit']}",
            f"- **Ошибки:** {', '.join('`' + e + '`' for e in c['errors'])}",
            "",
        ]
    lines += [
        "## WRITE (gated — в v1 НЕ зарегистрированы)",
        "",
        "| Tool | Risk | Статус |",
        "|---|---|---|",
    ]
    for name, c in WRITE_TOOLS_GATED.items():
        lines.append(f"| `{name}` | {c['risk']} | {c['status']} |")
    lines += [
        "",
        "Write-tools появятся после: (1) скоупа `mcp:write`, (2) idempotency-key, (3) решения владельца",
        "(для `execute_transaction` — STOP-GATE реального исполнения).",
        "",
    ]
    return "\n".join(lines)
