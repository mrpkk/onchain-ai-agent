# KARTA MCP — контракты tools

> AUTO-GENERATED: `docs/generate_mcp_contracts.py` (источник — `backend/src/mcp/contracts.py`).
> Транспорт: **streamable HTTP (stateless)**, `POST /mcp`, auth: `Authorization: Bearer karta_…`.
> Все ошибки — структурированные: `{"error": {"code", "message", "hint"}}`.

## READ (зарегистрированы в v1)

### `get_wallet` — Кошелёк агента

- **Описание:** Адрес кошелька, сеть, статус и тир агента (только свои агенты).
- **Параметры:** `agent_id: str (UUID агента владельца ключа)`
- **Возврат:** `{agent_id, name, wallet_address, chain_id, status, tier}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** адрес 0x…, chain_id — EIP-155 · —
- **Source/freshness:** postgres:agents · on_request
- **Rate limit:** 60/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`

### `get_balance` — Баланс агента

- **Описание:** Нативный баланс кошелька агента из реального RPC (ETH).
- **Параметры:** `agent_id: str`
- **Возврат:** `{agent_id, address, chain_id, balance_eth, block_number}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** ETH (wei → ETH) · —
- **Source/freshness:** rpc:ethereum (PublicNode) · on_request (блок сети)
- **Rate limit:** 30/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`, `NO_WALLET`, `CHAIN_UNSUPPORTED`, `RPC_UNAVAILABLE`

### `get_gas` — Газ (EIP-1559)

- **Описание:** Текущая цена газа сети агента (base fee + priority) из RPC.
- **Параметры:** `agent_id: str`
- **Возврат:** `{chain_id, base_fee_gwei, priority_fee_gwei, gas_price_gwei, block_number}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** gwei · —
- **Source/freshness:** rpc:ethereum (PublicNode) · on_request
- **Rate limit:** 30/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`, `CHAIN_UNSUPPORTED`, `RPC_UNAVAILABLE`

### `get_portfolio` — Портфель агента

- **Описание:** Честная v1-сводка: нативный баланс + сеть; агрегация токенов — Phase 5 (не выдумываем).
- **Параметры:** `agent_id: str`
- **Возврат:** `{agent_id, chain_id, native_balance_eth, tokens: null, note}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** ETH · —
- **Source/freshness:** rpc + postgres:agents · on_request
- **Rate limit:** 30/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`, `NO_WALLET`, `RPC_UNAVAILABLE`

### `get_transactions` — Транзакции агента

- **Описание:** История транзакций агента (Decision→Execution) из БД.
- **Параметры:** `agent_id: str, limit: int = 20 (1..100)`
- **Возврат:** `{items: [{id, status, tx_hash, value_eth, gas_used, created_at}], total}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** ETH, wei · limit ≤ 100
- **Source/freshness:** postgres:transactions · on_request
- **Rate limit:** 60/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`

### `agent_status` — Статус и здоровье агента

- **Описание:** Статус, тир, режим симуляции, health score, trust-ступень, дрейф.
- **Параметры:** `agent_id: str`
- **Возврат:** `{status, tier, simulation_mode, running, health, trust, drift}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** score 0–100 · —
- **Source/freshness:** postgres + runtime · on_request
- **Rate limit:** 60/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`

### `audit_log` — Sakshi-аудит агента

- **Описание:** Append-only события аудита агента с HMAC-цепочкой (hash/prev_hash).
- **Параметры:** `agent_id: str, limit: int = 50 (1..200)`
- **Возврат:** `{items: [{id, actor, event_type, payload, prev_hash, hash, created_at}], total}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** — · limit ≤ 200
- **Source/freshness:** postgres:audit_events (HMAC) · on_request
- **Rate limit:** 30/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`, `AUDIT_KEY_MISSING`

### `get_decision` — Решение + Replay

- **Описание:** Решение из Decision Diary и его вердикт по ТЕКУЩЕЙ политике (replay).
- **Параметры:** `decision_id: str (UUID решения владельца ключа)`
- **Возврат:** `{decision, then, now, verdict_changed}`
- **read/write:** read-only · **risk:** low · **cost:** free
- **Units/limits:** — · —
- **Source/freshness:** postgres:decisions + Dharma · on_request
- **Rate limit:** 60/min/key
- **Ошибки:** `UNAUTHORIZED`, `NOT_FOUND`

## WRITE (gated — в v1 НЕ зарегистрированы)

| Tool | Risk | Статус |
|---|---|---|
| `simulate_transaction` | low | gated (v1 не зарегистрирован) |
| `create_plan` | medium | gated |
| `request_approval` | medium | gated |
| `execute_transaction` | high | gated (STOP-GATE: реальное исполнение) |
| `agent_pause` | medium | gated |
| `agent_kill` | high | gated |

Write-tools появятся после: (1) скоупа `mcp:write`, (2) idempotency-key, (3) решения владельца
(для `execute_transaction` — STOP-GATE реального исполнения).

