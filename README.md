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

## 🔌 API (18 маршрутов + WebSocket; сверено с кодом)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/v1/auth/register` | Регистрация (Argon2id) |
| POST | `/api/v1/auth/token` | Логин → access+refresh (15м/7д) |
| POST | `/api/v1/auth/refresh` | Ротация пары; reuse → отзыв семьи |
| POST | `/api/v1/auth/revoke-all` · `/api/v1/auth/logout` | Отзыв всех сессий |
| POST/GET | `/api/v1/agents` | Создать / список агентов |
| GET | `/api/v1/agents/{id}` | Карточка агента |
| POST | `/api/v1/agents/{id}/start` · `/stop` | Запуск / пауза |
| POST | `/api/v1/agents/{id}/goal` | Постановка цели |
| POST | `/api/v1/agents/{id}/kill-switch` | Экстренная остановка |
| GET | `/api/v1/agents/{id}/transactions` | История транзакций |
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
# Backend: 116 тестов (security, dharma, JWT, health, persistence, sakshi, ws, llm-router, mempool)
backend/.venv/bin/python -m pytest backend/tests -q

# Контракты: 56 тестов (hardhat)
cd smart-contracts && npx hardhat test
```

## 🏗 Архитектура (кратко)

```
Human → REST /api/v1 + WS /ws → [Dharma Engine] → [Risk] → [Simulator*] → [Approval*] → [Karma Engine*] → Chain
                                        ↓                                                  ↓
                                  Sakshi Log (HMAC, append-only)  ←  Decision Diary (decisions)
* Phase 3/5 — в разработке; сейчас: simulation-mode + policy-гейт + kill-switch
```

**Инварианты:** LLM не получает ключ; tx не подписывается без policy-вердикта и симуляции (Phase 3);
любая ошибка → hold + ask_human; ни один слой не контролирует pipeline единолично.

## 📚 Документы

- `PROGRESS.md` — мега-контекст, реестр слайсов, журнал
- `docs/AUDIT_REPORT.md` — actual-vs-claimed аудит
- `docs/THREAT_MODEL.md` — STRIDE T1–T12
- `docs/ARCHITECTURE_CURRENT.md` — фактическая архитектура
- `smart-contracts/` — Solidity 0.8.20 + Hardhat

---

> **Дисклеймер:** не является финансовой рекомендацией. Автономный агент действует в границах
> политик владельца; реальное исполнение — только после отдельного решения (STOP-GATE).
