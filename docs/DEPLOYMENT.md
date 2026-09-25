# KARTA — Deployment Guide

> Продакшн-развёртывание, dev-режим, переменные окружения, адреса тестнета.
> Секреты — только в `~/.env` (chmod 600), никогда в репозитории.

## 1. Требования

| Компонент | Версия | Зачем |
|---|---|---|
| Python | 3.12+ | backend |
| PostgreSQL | 16 | БД (dev — docker на 5433, системный PG занят) |
| Docker | любой | PG/compose (dev и прод) |
| Node.js | 20+ | контракты (Hardhat) |
| Foundry (опция) | 1.8+ | anvil-интеграции, fork-тесты |

## 2. Dev-режим (локально)

```bash
# 1) PostgreSQL (порт 5433)
docker compose up -d postgres

# 2) Зависимости
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt

# 3) Миграции
cd backend && DATABASE_URL=postgresql+asyncpg://agent:agent@127.0.0.1:5433/onchain_ai \
  .venv/bin/alembic upgrade head && cd ..

# 4) Запуск (dev)
DEBUG=true backend/.venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8090  # из backend/
# Swagger: http://127.0.0.1:8090/docs · Кокпит: http://127.0.0.1:8090/

# 5) Тесты
backend/.venv/bin/python -m pytest backend/tests -q --cov=src --cov-fail-under=80
cd smart-contracts && npx hardhat test
```

### Dev как systemd-юнит (используется на этой машине)

```bash
systemd-run --user --unit=karta-dev --collect --working-directory=/home/iamthat/onchain-ai-agent/backend \
  --setenv=DEBUG=true --setenv=DATABASE_URL=postgresql+asyncpg://agent:agent@127.0.0.1:5433/onchain_ai \
  --setenv=SAKSHI_AUDIT_KEY=... \
  .venv/bin/uvicorn src.api.main:app --host 127.0.0.1 --port 8090
systemctl --user restart karta-dev   # управление
```

## 3. Прод (docker compose)

```bash
cp .env.example .env   # заполнить секреты (или смонтировать ~/.env)
docker compose up -d --build          # backend (8080) + postgres
docker compose --profile optional up -d   # + redis (multi-worker)
```

- Dockerfile: `uvicorn --host 0.0.0.0 --port 8080`; миграции применять до старта (`alembic upgrade head`).
- Health: `GET /api/v1/health` (честный: database/redis/rpc/private_rpc/llm/keyvault/telegram).
- Статика/PWA — из `backend/src/api/static/`.

## 4. Переменные окружения (ключевые)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | PostgreSQL async DSN |
| `JWT_SECRET_KEY` | подпись токенов (в prod обязателен, `openssl rand -hex 32`) |
| `DEBUG` | dev-режим (в prod выключен; security-гейт старта) |
| `GIGACHAT_AUTH_KEY` | LLM (primary), далее DeepSeek/Qwen/… |
| `SAKSHI_AUDIT_KEY` | HMAC-ключ аудита |
| `WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY` | тестнет-кошелёк (подписи сервисов) |
| `KARTA_TELEGRAM_BOT_TOKEN` / `TG_KARTA_BOT` | Telegram-approve (создание бота — владелец) |
| `KARTA_MCP_ALLOWED_HOSTS` | Host-allowlist MCP (DNS-rebinding) |
| `PRIVATE_RPC_ENABLED` | private RPC для mainnet-отправок (Flashbots/MEV Blocker) |
| `BRIDGE_EXECUTION_ENABLED` | исполнение bridge (STOP-GATE реальных средств) |
| `KARTA_AA_SESSION_KEY` | demo session key для ERC-4337 |
| `KARTA_X402_DEMO_PAYER_KEY` | демо-плательщик x402 |

Адреса контрактов задаются в `backend/src/config/settings.py` (дефолты — Sepolia-деплой), переопределяются env.

## 5. Тестнет-деплой (Sepolia, chainId 11155111)

| Контракт | Адрес |
|---|---|
| AgentRegistry (ERC-8004) | `0x773945A9eA400e9c8704a2c02AAAbF449cFc20E5` |
| Escrow | `0xB73c9F99d40116501C0a18c4019Ac8E91ED7dE8a` |
| RicardianAgreement | `0x153010a3f18cf363A87364BB8182Fc13ABF95dF2` |
| MockERC20 (mUSDC) | `0x212774d426519437d5Eb1126fE382fC7b7cCe7B0` |
| xUSDC (EIP-3009, x402) | `0x0eB3e17862A108Bbbc91989e6Ca1a3ed16f69710` |
| MockDEX (swap) | `0xd11243Bd90EBc88e3A7D4eeA364Ee204A3aD509d` |
| KartaEntryPoint (4337) | `0x40a52b4959cCA148594D8Bd29ccE4C292E8730B0` |
| KartaSmartAccount | `0x2DE1302269746DaD1CC0f828030893D404AC572e` |
| MockPaymaster | `0x70B46CcD59E168b381E19De316F7064771262d55` |

Деплой-скрипты: `smart-contracts/scripts/deploy.js` (основные), `scripts/ricardian_anvil_flow.py`, `scripts/swap_anvil_flow.py`, `scripts/registry_anvil_flow.py` (локальные циклы).

## 6. Интеграции

- **MCP**: `POST /mcp`, ключи `karta_` через `POST /api/v1/api-keys` → см. `docs/MCP.md`.
- **x402-демо**: `GET /api/v1/x402/demo/premium` → см. `docs/X402.md`.
- **Мониторинг**: `scripts/e2e_live.py` (полный live-регресс одной командой).

## 7. Бэкапы и эксплуатация

- Бэкап: `bash /home/iamthat/Документы/opencode/shared/full-backup.sh` (локально + GDrive).
- PG-дамп: `docker exec karta-postgres pg_dump -U agent onchain_ai > backup.sql`.
- Секреты не коммитить: `.gitignore` + gitleaks в CI.
