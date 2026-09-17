# ARCHITECTURE_CURRENT.md — фактическая архитектура (as-is, на 16.09.2026)

> S0-03 · Источник: аудит `docs/AUDIT_REPORT.md` · Evidence: `file:line` · Статус: архив, не цель.
> Читать вместе с `docs/AUDIT_REPORT.md` (actual-vs-claimed) и целевой архитектурой SPEC §5.

## 1. Компоненты (как есть)

```
backend/src/
├── api/
│   ├── main.py        812 строк: FastAPI + auth + CRUD агентов + HTML-дашборд (inline)
│   └── models.py      pydantic-модели ответов
├── agent/
│   ├── core.py        OnChainAgent — asyncio-цикл _tick() каждые 60с, состояние, аудит-лог (in-memory)
│   ├── perception.py  BlockchainPerception (4 сети: eth/bsc/polygon/sepolia) · PriceOracle (CoinGecko) · MempoolMonitor (заглушка)
│   ├── reasoning.py   LLMReasoner (GigaChat primary → Mistral fallback) · RiskAssessor · AgentDecision
│   ├── planning.py    AgentPlanner (стратегии yield/arbitrage/ricardian/generic) · Plan/PlanStep
│   └── execution.py   WalletManager (ключ) · TransactionExecutor (retry, газ×1.2, nonce-кэш) · SpendingLimit
├── security/keyvault.py  Fernet-keystore (~/.onchain-agent/keys.enc, chmod 600)
└── config/settings.py    pydantic-settings + validate_security() (гейт при старте)
```

## 2. Поток данных (as-is)

```
HTTP → api/main.py (JWT, in-memory dicts)
        → OnChainAgent._tick()
            ├─ _gather_state(): блок, газ, цены, баланс
            ├─ LLMReasoner.decide() → JSON {action, params, reasoning, confidence, risk_level}
            ├─ RiskAssessor.assess() (пороги: >1 ETH, >50% баланса, газ >500k, лимиты)
            ├─ requires_approval? → статус awaiting_approval (и всё)
            ├─ simulation_mode? (default True) → лог «Would execute» (и всё)
            └─ _execute_decision() → TransactionExecutor (3 retry, legacy-gas)
```

## 3. Хранилище (as-is)

| Слой | Реальность |
|---|---|
| Пользователи/агенты/транзакции | **in-memory dict'ы** `_users_db`, `_agents_db`, `_transactions_db` (`api/main.py:67-69`) — теряются при рестарте |
| Состояние агента | JSON в `~/.onchain-agent/state/{agent_id}.json` |
| Ключи | Fernet-keystore `~/.onchain-agent/keys.enc` (реально работает, 6 тестов) |
| Аудит-лог | список в памяти `_audit_log` (лимит 1000, теряется) |
| PostgreSQL/Redis | **заявлены, не подключены**; `/health` возвращает `redis_connected=True` хардкодом (`api/main.py:304`) |

## 4. On-chain (as-is)

- **Сети:** Ethereum, BSC, Polygon, Sepolia (RPC захардкожены в `perception.py`).
- **Подпись:** legacy-gas tx; nonce кэш per-chain; `eth_account.Account.from_key`.
- **Approve:** `2**256-1` по умолчанию (`execution.py:261`).
- **Симуляция:** `eth_call` (`simulate_transaction`), без fork и diff.
- **Контракты:** `AgentRegistry.sol` (ERC-8004-задел, 27 тестов) · `Escrow.sol` · `RicardianAgreement.sol` (2-of-3, без тестов).

## 5. Аутентификация (as-is)

JWT HS256 60 мин, без refresh/revocation (`api/main.py:103-109`); пароли `sha256+salt` самописный (`main.py:52-59`); RBAC нет; rate-limit нет.

## 6. Инфраструктура (as-is)

CI: pytest `test_security.py` (6 тестов) + grep-скан приватников. Docker Compose с pg16/redis7 (не используется в dev). systemd-юнитов нет. Тестов: 6.

## 7. Разрывы до целевой архитектуры (SPEC §5)

Всё из `docs/AUDIT_REPORT.md` §2–3: in-memory вместо PG (P1), нет Dharma/Simulator/Sakshi-БД, LLM без structured output, дашборд v1 (vanilla), нет MCP/WS/RBAC/rate-limit. P0-дефекты: `core.py:98-99`, `execution.py:261`, `main.py:52-59`, `main.py:304`, контракты.
