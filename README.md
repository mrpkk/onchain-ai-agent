# OnChain AI Agent — Автономный AI-агент с EVM-кошельком

**AI-агент, который владеет криптокошельком, подписывает контракты и выполняет on-chain операции.**
Полный жизненный цикл: восприятие → рассуждение → планирование → исполнение.

## ✨ Возможности

### 🧠 AI-ядро
- **Perception** — мониторинг блокчейна, ценовые оракулы, мемпул
- **Reasoning (CoT)** — Chain-of-Thought рассуждения через Mistral AI
- **Planning** — автоматическое построение плана действий
- **Execution** — подпись и отправка транзакций

### 🔗 On-Chain
- Multi-chain: Ethereum, BSC, Polygon, Sepolia
- WalletManager — управление кошельками (create/import/list)
- TransactionExecutor — отправка ETH, вызов контрактов, approve
- Spending limits — дневные и per-tx лимиты
- Simulation mode — тест без реальных средств

### 📜 Смарт-контракты (Solidity)
- **AgentRegistry.sol** — реестр AI-агентов на блокчейне
- **Escrow.sol** — условное депонирование
- **RicardianAgreement.sol** — юридически обязывающие соглашения

### 🔐 Безопасность
- JWT аутентификация
- Spending limits (daily + per-tx)
- Blacklist/whitelist адресов
- Kill switch — экстренная остановка агента
- Audit log — все действия логируются

## ⚡ Быстрый запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# Настройка .env (скопируйте .env.example)
# Запуск
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

## 🔌 API (16 эндпоинтов)

```bash
POST /api/v1/auth/register     — регистрация
POST /api/v1/auth/token        — JWT токен
POST /api/v1/agents            — создать агента
GET  /api/v1/agents            — список агентов
POST /api/v1/agents/{id}/start — запустить агента
POST /api/v1/agents/{id}/goal  — поставить цель
POST /api/v1/agents/{id}/kill-switch — экстренная остановка
GET  /api/v1/agents/{id}/transactions — история транзакций
```

## 💰 Монетизация

| Вариант | Цена |
|---------|------|
| **Self-hosted license** (исходный код) | $1000-3000 |
| **SaaS** (API-доступ) | $100-500/мес |
| **Enterprise** (кастомизация + поддержка) | $5000-15000 |
| **Smart contract audit + deploy** | $2000-5000 |

## 🏗 Технологии

| Компонент | Технология |
|-----------|-----------|
| **Framework** | FastAPI + SQLAlchemy |
| **AI** | Mistral AI (OpenAI-compatible) |
| **Blockchain** | Web3.py (6 EVM chains) |
| **Auth** | JWT + Passlib |
| **Contracts** | Solidity 0.8.28 |
