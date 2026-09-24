# KARTA — onchain-ai-agent

> **Trust layer между AI и ончейн-действием.** Агент предлагает → детерминированная политика
> (**Dharma Engine**) разрешает → симуляция подтверждает → человек аппрувит → **Karma Engine**
> исполняет → **Sakshi Log** доказывает.
>
> Статус: **v2 в разработке** (ветка `feature/v2-modernization`). Тесты: **116 backend + 56 контрактов**.
> Канон-спека: `Документы/work/projectBooks/OnChainKartaSPEC.md`.

---

## ✅ Что реально работает (проверено тестами)

| Область | Статус |
|---|---|
| **Auth** | Argon2id; JWT access 15 мин + refresh 7 дней (ротация, reuse-detection → отзыв семьи, revoke-all); rate-limit логина 5/мин; legacy-sha256-миграция |
| **Хранилище** | PostgreSQL 16 (14 таблиц, Alembic-миграции); данные переживают рестарт (тест «engine reset = restart») |
| **Dharma Engine** | 15 правил (лимиты per-tx/daily/velocity, газ-кап, slippage, black/whitelist, окно, breakers, approve-гигиена); вердикты allow/deny/require_approval; гейт в ОБОИХ путях исполнения; `DHARMA_ENFORCE=off` для отката |
| **Approve** | Только точные суммы; `2^256-1` заблокирован (`INFINITE_APPROVE_BLOCKED`); `revoke_approve` |
| **KeyVault** | Ключ только через vault (lazy-init), `core.py` не читает ключ из конфига (guard-тест) |
| **Безопасность исполнения** | Simulation-mode (дефолт); реальное исполнение — за флагом (READ+SIMULATE+PROPOSE) |
| **Kill switch** | soft/hard, терминальный (без auto-resume), drill-тесты |
| **Sakshi Log** | HMAC-цепочка (`prev_hash‖canonical(payload)`), append-only (PG-триггер), экспорт `json\|csv` |
| **Decision Diary** | Каждое решение (action/reasoning/confidence/risk/policy_verdict) пишется в БД |
| **Live-события** | `WS /ws?token=` — agent.status, decision.proposed (fan-out, 4401 при невалидном токене) |
| **LLM** | Цепочка **GigaChat → DeepSeek → Qwen → агрегатор → Ollama**; structured output (pydantic) + repair + circuit breaker 3×60с; fail-safe `ask_human` |
| **Mempool** | Реальный сканер блоков: watch-фильтр адресов + газ-тренд; честный `rpc_unavailable` без выдумок |
| **Health** | `/health` + `/health/deep`: реальные TCP/RPC/LLM/KeyVault-проверки → ok/degraded/down |
| **Контракты** | AgentRegistry + Escrow + RicardianAgreement: 56 hardhat-тестов, Slither (`fail-on: high`) в CI |

## 🚧 Чего ещё нет (честно)

- Реальное исполнение транзакций, swap/bridge/deploy — Phase 5 (STOP-GATE)
- Кокпит-UI, Telegram-approve, i18n — Phase 4
- ERC-4337 session keys, private RPC, MEV-защита — Phase 5
- MCP-сервер наружу (read-tools) — Phase 6
- RefreshStore пока in-memory (таблица `refresh_tokens` готова — миграция слоем позже)

## 🔌 API (37 маршрутов + WebSocket; авто-перечень — `docs/API.md`)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/v1/auth/register` · `/token` · `/refresh` · `/revoke-all` · `/logout` | Argon2id, JWT-пара с ротацией и reuse-detection |
| POST/GET | `/api/v1/agents` | Создать / список агентов (тиры 0–3, авто-политика тира) |
| GET | `/api/v1/agents/{id}` | Карточка агента |
| POST | `/api/v1/agents/{id}/start` · `/stop` · `/heartbeat` | Жизненный цикл (+ dead-man switch) |
| POST | `/api/v1/agents/{id}/goal` · `/intent` · `/intent/confirm` | Цель; чат-задача NL→intent с Dharma-превью |
| GET/PUT | `/api/v1/agents/{id}/policy` · POST `/policy/from-text` · `/policy/simulate` | Версии Dharma-политики; правила словами; impact-симулятор |
| GET | `/api/v1/agents/{id}/decisions` · `/pending` · `/audit` · `/drift` | Decision Diary; undo-очередь; Sakshi; дрейф |
| GET | `/api/v1/agents/{id}/reports/summary` · `/export.csv` | Health/Trust/дрейф-сводка; CSV (decisions/transactions/audit) |
| GET/POST | `/api/v1/approvals` · `/approvals/{id}/approve|reject` · `/pending/{id}/cancel` | Approvals-inbox (web=Telegram, единый путь) |
| GET/POST/PUT | `/api/v1/decisions/{id}` | Replay: текущий вердикт vs сохранённый |
| POST | `/api/v1/agents/{id}/kill-switch` | Экстренная остановка (soft/hard, терминальная) |
| GET | `/api/v1/agents/{id}/transactions` | История транзакций |
| GET/POST/DELETE | `/api/v1/api-keys` | API-ключи `karta_` для MCP (scope mcp:read) |
| POST | `/mcp` | MCP-сервер (streamable HTTP, stateless, read-only v1) — см. `docs/MCP.md` |
| GET/POST | `/api/v1/ricardian/*` | Ricardian 2-of-3: соглашения, подписи, вехи, споры (Sepolia) |
| GET/POST | `/api/v1/agents/{id}/registry` | ERC-8004-паспорт: регистрация/верификация/репутация + бейджи |
| GET | `/api/v1/registry/agents/{id}/metadata` | Публичный паспорт агента (metadataURI, без auth) |
| GET/POST | `/api/v1/escrow/*` | Аренда агентов: эскроу-оплата, release/refund/dispute/resolve (Sepolia) |
| GET | `/api/v1/x402/demo/premium` | x402-демо: 402 → EIP-3009-подпись → сеттлмент (Sepolia, токен без ценности) |
| GET | `/api/v1/chains` | Multi-chain реестр: 6 сетей (ETH/Sepolia/Base/Base Sepolia/BSC/Polygon) + health |
| GET/POST | `/api/v1/swap/*` | Swap: котировка, slippage-guard, исполнение (MockDEX/Uniswap-V2, Sepolia) |
| GET | `/api/v1/health` · `/health` · `/health/deep` | Честные проверки компонентов |
| WS | `/ws?token=<access>` | Live-события |
| GET | `/docs` · `/openapi.json` | OpenAPI/Swagger |

## 🚀 Быстрый старт

```bash
# 1) PostgreSQL (dev): контейнер на 5433 (системный PG занимает 5432)
docker compose up -d postgres        # или: docker run -d --name karta-postgres \
                                     #   -e POSTGRES_USER=agent -e POSTGRES_PASSWORD=agent \
                                     #   -e POSTGRES_DB=onchain_ai -p 5433:5432 postgres:16-alpine

# 2) Зависимости
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt

# 3) Схема
cd backend && DATABASE_URL=postgresql+asyncpg://agent:agent@127.0.0.1:5433/onchain_ai \
  .venv/bin/alembic upgrade head

# 4) Запуск
DEBUG=true .venv/bin/uvicorn src.api.main:app --port 8000   # из backend/

# 5) Swagger: http://127.0.0.1:8000/docs
```

### Ключевые переменные окружения (только `~/.env`, chmod 600)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://agent:agent@127.0.0.1:5433/onchain_ai` |
| `JWT_SECRET_KEY` | `openssl rand -hex 32` (обязательно в prod) |
| `ONCHAIN_MASTER_KEY` | мастер-ключ KeyVault |
| `SAKSHI_AUDIT_KEY` | ключ HMAC-цепочки аудита |
| `GIGACHAT_AUTH_KEY` | GigaChat (первичный LLM) |
| `DEEPSEEK_API_KEY_*` | DeepSeek (fallback) |

## 🧪 Тесты

```bash
# Backend: 307 тестов + coverage-гейт 80%
backend/.venv/bin/python -m pytest backend/tests -q --cov=src --cov-fail-under=80

# Контракты: 56 тестов (hardhat)
cd smart-contracts && npx hardhat test

# Live E2E-смоук (13 проверок) против запущенного сервера:
python3 scripts/e2e_live.py     # KARTA_E2E_BASE/USER/PASS — при необходимости
```

## 🏗 Архитектура (кратко)

```
Human → REST /api/v1 + WS /ws → [Dharma Engine] → [Simulation] → [Timelock/Approval] → [Karma Engine] → Chain*
                                        ↓                                                ↓
                                  Sakshi Log (HMAC, append-only)  ←  Decision Diary (decisions)
* Реальное исполнение on-chain — Phase 5 (STOP-GATE); сейчас: тиры 0–1 simulation-mode, тиры 2–3 за гейтами
```

**Инварианты:** LLM не получает ключ; tx не подписывается без policy-вердикта и симуляции;
любая ошибка → hold + ask_human; ни один слой не контролирует pipeline единолично.

## 📚 Документы

- `PROGRESS.md` — мега-контекст, реестр слайсов, журнал
- `docs/AUDIT_REPORT.md` — actual-vs-claimed аудит
- `docs/THREAT_MODEL.md` — STRIDE T1–T12
- `docs/ARCHITECTURE_CURRENT.md` — фактическая архитектура (до модернизации)
- `docs/ARCHITECTURE.md` · `docs/SECURITY.md` — as-built архитектура и security-posture
- `docs/API.md` — перечень API (генератор `docs/generate_api_md.py`)
- `docs/MCP.md` · `docs/MCP_TOOL_CONTRACTS.md` — MCP-сервер: подключение и контракты (генератор `docs/generate_mcp_contracts.py`)
- `docs/X402.md` — x402-демо (тестнет): поток, запуск, честные ограничения
- `smart-contracts/` — Solidity 0.8.20 + Hardhat

---

> **Дисклеймер:** не является финансовой рекомендацией. Автономный агент действует в границах
> политик владельца; реальное исполнение — только после отдельного решения (STOP-GATE).
