# PROGRESS.md — KARTA v2 (onchain-ai-agent) · МЕГА-КОНТЕКСТ

> **Единственная точка правды о прогрессе.** Диалог не хранит состояние — оно живёт здесь.
> **Канон-спека:** `~/Документы/work/projectBooks/OnChainKartaSPEC.md` (v3, судья-синтез 5 моделей) · **Эталон:** `OnChain_AI_Agent_MODERNIZATION.md` · **Книга:** `OnChain_AI_Agent.md`
> **Репозиторий:** `/home/iamthat/onchain-ai-agent` · **Ветка:** `feature/v2-modernization` (main заморожен до мержа)
> **Правило старта:** слайс исполняется ТОЛЬКО после прямой команды владельца («запускай S1-01»). Обсуждение ≠ команда (прецедент 16.09).
> **Формат слайса:** код + тест + docs + зелёный прогон + отметка здесь (хэш) + коммит (`<type>(<scope>): <subject>`) + push.
> **Легенда:** `[ ]` todo · `[~]` in progress · `[x]` done (hash) · `[!]` blocked (причина).

---

## 🎯 МИССИЯ И КОНТЕКСТ ПРОДУКТА (читать первым в каждой сессии)

**KARTA** (санскр. kartā = «деятель, агент») — trust-слой между человеком, AI и ончейн-действием. Не «AI-трейдинг-бот», а **доверенная автономия**: агент действует по правилам владельца, симулирует до подписи, отчитывается за каждый шаг.

**Система имён (утверждена):** KARTA (продукт) · **Karma Engine** (исполнение) · **Dharma Engine** (политики, детерминированный) · **Sakshi Log** (аудит, append-only). Формула: «Карта совершает карму, ограниченную дхармой, под взглядом свидетеля».

**Пять принципов:** Intent First → Safety by Default → Simulation Before Execution → Policy Over AI → Auditability.
**Позиционирование:** «Твой агент. Твои правила. Твои ключи.» · слайс-гейт: 12 абсолютных правил SPEC §2.
**Кредо UX:** «нанимаешь оператора, а не просишь чатбота» — мандат → мелкое финансирование → дневник → увольнение при дрейфе.

## 🤝 КЛЮЧЕВЫЕ ДОГОВОРЁННОСТИ С ВЛАДЕЛЬЦЕМ (append-only)

1. **16.09.2026** — имя **KARTA** утверждено; система karma/dharma/sakshi одобрена. Лого: 3 концепта в `branding/` (выбор владельца — STOP GATE №1).
2. **16.09.2026** — **Mistral вычеркнут** (заблокирован в РФ). Цепочка: **GigaChat (primary) → DeepSeek → Qwen → РФ-агрегаторы (GPTunneL/Chad/provod.ai) → Ollama**. Строки `MISTRAL*` в `~/.env` не трогать.
3. **16.09.2026** — **бюджет тестов 0₽**: только anvil/hardhat 31337 + Sepolia-краник (0.06 ETH/сутки, критичные e2e). Платные сети/провайдеры — только по отдельному решению.
4. **16.09.2026** — **правило старта**: обсуждение ≠ команда; каждая фаза/слайс — только по прямой команде. Прецедент: старт Phase 0 без команды остановлен владельцем.
5. **18.09.2026** — SPEC v3 (судья-синтез) канонизирован; убраны противоречия (JWT 15м/7д, 4 тира, Hardhat+anvil, без SSE).
6. **16.09.2026** — ключи `backend/.env` (права 664!) → план переноса в `~/.env` chmod 600 (STOP GATE, ждёт решения).
7. Футуристики: комбо **F3→F2→F1→F8→F5** рекомендовано; внедрение — только по решению (FUTURE LAB).

## 🧭 ТЕКУЩИЙ ШАГ (обновлять при каждом слайсе)

**Статус:** P0 закрыт 100%; **P1 «Безопасность» — 8/9 слайсов закрыто** (S1-02 · S1-04 · S1-05 · S1-06 · S1-08 · S1-09 · S1-03 · S1-07). Тесты: **140 зелёных** (backend 84 + контракты 56). Раннеры: `backend/.venv/bin/python -m pytest` и `npx hardhat test` (smart-contracts).
**Ждёт владельца:** S1-01 — перенос `backend/.env` → `~/.env` (chmod 600). По команде «да» — финальный слайс и P1 закрыта полностью.
**Следом (P2, по команде):** S2-01 PG+Alembic (agents/decisions/audit/RefreshStore → БД), S2-02 Sakshi Log с HMAC-цепочкой, S2-03 WS-события, S2-05 LLMProvider+structured output, S2-07 Mempool real/NOT_IMPLEMENTED, S2-08 README=код.
**Открытые STOP-GATE (6):** (1) execution-граница v2 = READ+SIMULATE+PROPOSE? (2) PG локально через docker-compose? (3) DeepSeek-ключ в `~/.env`? (4) перенос `backend/.env` → `~/.env` chmod 600? (5) футуристики F3→F2→F1→F8→F5? (6) фронтенд A (server-rendered, рекомендован) или B (React SPA)?

---

## 📊 БАЗОВАЯ ЛИНИЯ (аудит 16.09, evidence)

**Тесты:** 6/6 security-тестов зелёные (system python3.14, pytest 9.0.2; `.venv` без pytest).
**Контракты:** тесты только AgentRegistry (27 describe/it); Escrow/RicardianAgreement — без тестов.
**P0-блокеры:**

| # | Дефект | Evidence | Слайс |
|---|---|---|---|
| P0-1 | Прямой доступ к приватному ключу из конфига | `agent/core.py:98-99` | S1-04 |
| P0-2 | Max-approve `2**256-1` по умолчанию | `agent/execution.py:261` | S1-05 |
| P0-3 | Самописный sha256+salt для паролей | `api/main.py:52-59` | S1-02 |
| P0-4 | Фейковый Redis-health (`redis_connected=True`) | `api/main.py:304` | S1-09 |
| P0-5 | Контракты без тестов/Slither | `smart-contracts/test/` | S1-07 |
| P1 | секреты в `backend/.env` (664), README 16 vs 13 эндпоинтов, in-memory БД, JWT без refresh | — | S1-01, S2-01, S2-08 |

**Артефакты аудита:** `docs/AUDIT_REPORT.md`, `docs/ARCHITECTURE_CURRENT.md`, `docs/THREAT_MODEL.md`, `PROGRESS.md`.

---

## 📋 РЕЕСТР СЛАЙСОВ (P0–P7)

### P0 — Аудит и правда (закрыт, без правок кода)
- [x] S0-01 Инвентарь репозитория + PROGRESS.md — `dbf5de4`
- [x] S0-02 `docs/AUDIT_REPORT.md` (actual-vs-claimed, P0–P3, file:line) — `213a1bf`
- [x] S0-03 `docs/ARCHITECTURE_CURRENT.md` (фактическая архитектура) — `f40b6c6`
- [x] S0-04 `docs/THREAT_MODEL.md` (STRIDE, T1–T12, контрмеры→тесты) — `f40b6c6`
- [x] S0-05 STOP-GATE вопросы владельцу (6 шт.) → **STOP** — этот файл
- [x] Брендинг-концепты: `branding/karta-chakra.svg`, `karta-monogram.svg`, `karta-shield.svg` — `dbf5de4`

### P1 — Безопасность (цель 1–2 нед; каждый слайс — по команде)
- [ ] S1-01 Секреты: `backend/.env` → `~/.env` (chmod 600), CI secret-scan (gitleaks + entropy)
- [x] S1-02 Argon2id (passlib) + миграция legacy sha256 при логине + 8 тестов — `c0a6c97`
- [x] S1-03 JWT-пара: `security/tokens.py` (access 15м + refresh 7д, type-claim, jti, family_id), ротация на каждом refresh, reuse-detection → отзыв всей семьи, эндпоинты `/auth/refresh` · `/auth/logout` · `/auth/revoke-all`, rate-limit логина 5/мин/IP (`api/ratelimit.py`), 14 тестов (unit+API) — `b5c81f5`. RefreshStore пока in-memory — PG-персистентность в S2-01.
- [x] S1-04 KeyVault-миграция: lazy `_ensure_wallet()`, guard-тест + поведенческие тесты (executor retry при RPC) — `7d24267`
- [x] S1-05 Scoped approve: `_to_approve_amount` блокирует None/negative/max, `revoke_approve`, amount-паспорт из решений/планов — `f2bc393`
- [x] S1-06 Dharma MVP: `security/dharma/` (dsl/compiler/ctx/evaluator), 15 правил, гейт в обоих путях, negative-тесты, `DHARMA_ENFORCE=off` — `fbdd352`
- [x] S1-07 Контракты: **обнаружено, что контракты не компилировались вовсе**; исправлены 4 класса дефектов: (1) `bool ok = safeTransfer` ×5 — OZ v5 возвращает void; (2) коллизия `error MilestoneDisputed` ↔ `event MilestoneDisputed` (твердый запрет Solidity); (3) `signers` смешивал членство и подпись — ВСЕ участники помечались «уже подписавшими», активация 2-of-3 была **невозможна** → разделены `members`/`signers`; (4) guard дубликата имени `nameToAgentId != 0` не ловил id=0 → `_nameUsed`. Добавлены `contracts/mocks/MockERC20.sol`, тесты Escrow (17) + Ricardian (22) + AgentRegistry (17) = **56 зелёных**; CI: backend-сьют + `npx hardhat test` + Slither (`fail-on: high`) + Aderyn (soft — калибровка на subdir) — `0746648` + `cf2773f` + `2881461`
- [x] S1-08 Kill-switch drill: `trigger_kill_switch(soft/hard)`, блок исполнения во всех путях, терминальный hard (без auto-resume), 5 тестов — `82f7826`
- [x] S1-09 Честный `/health` + `/health/deep`: реальные TCP/RPC/LLM/KeyVault, статусы ok/degraded/down — `1d8f00b`

### P2 — Честный фундамент
- [ ] S2-01 PG16 + async SQLAlchemy 2.0 + Alembic + repositories; рестарт не теряет данные (14 таблиц: SPEC §6.1)
- [ ] S2-02 Sakshi Log в БД: append-only, HMAC-цепочка `hash_n = HMAC(audit_key, prev_hash ‖ canonical(payload))`, экспорт
- [ ] S2-03 WebSocket `/ws`: decision.proposed, approval.requested, tx.submitted, tx.confirmed, agent.status, provider.degraded
- [ ] S2-04 Redis: решение по use-case (кэш цен/WS pub-sub/rate-limit) или удаление из compose/docs
- [ ] S2-05 LLMProvider + LLMRouter + structured output (pydantic `AgentDecision`) + circuit breaker
- [ ] S2-06 Трейсинг решений: request_id/agent_id/latency/tokens/cost/prompt-version
- [ ] S2-07 MempoolMonitor: реальный (pending-tx + gas-тренд) или честно NOT_IMPLEMENTED
- [ ] S2-08 README=код: таблица эндпоинтов из OpenAPI

### P3 — Policy и Simulation
- [ ] S3-01 Dharma DSL YAML + валидатор + вердикты в UI
- [ ] S3-02 Simulation-гейт: `submit()` принимает только `SimulationReceipt(ok=True, ttl≤120с)`; anvil fork, diff, gas
- [ ] S3-03 Timelock/undo-window для необратимых действий
- [ ] S3-04 Dead man's switch (нет heartbeat N часов → hard kill)
- [ ] S3-05 Approval Guardian UI (сканер allowances SAFE/REVIEW/HIGH RISK)

### P4 — Friendly-ядро + бренд (2–3 нед)
- [ ] S4-01 Дизайн-система (токены SPEC §11, все состояния компонентов)
- [ ] S4-02 Кокпит (статус-бар/план-таймлайн/лента решений/спарклайны)
- [ ] S4-03 Chat-first (NL → превью → подтверждение → квитанция)
- [ ] S4-04 Onboarding ≤5 мин, тиры 0–3, demo-режим по умолчанию
- [ ] S4-05 Decision diary + «Почему?» + Decision Transparency Card
- [ ] S4-06 Telegram inline-approve (aiogram; Telegram не обходит policy)
- [ ] S4-07 PnL + CSV (cost basis, realised/unrealised)
- [ ] S4-08 Landing + docs + i18n RU/EN
- [ ] S4-09 KARTA-ассеты (после выбора лого владельцем)
- [ ] S4-10 Фичи-дифференциаторы: Intent→Guarantee, Counterfactual Engine, Agent Health Score, Autonomy Drift, Trust Ladder, Decision Replay, Policy Simulator

### P5 — Исполнение 2.0
- [ ] S5-01 Swap (1inch/агрегатор + slippage-guard) · S5-02 Bridge · S5-03 Deploy
- [ ] S5-04 EIP-1559 + газ-оракул · S5-05 Private RPC (Flashbots-класс) + jitter
- [ ] S5-06 ERC-4337: smart account + session keys (TTL, revoke) + paymaster + social recovery
- [ ] S5-07 Multi-chain adapter (сеть = config {rpc[], explorer, finality, health})

### P6 — Агент-экономика (по решению)
- [ ] S6-01 ERC-8004 live + бейджи · S6-02 Аренда через Escrow · S6-03 Ricardian 2-of-3 UI · S6-04 MCP-сервер наружу · S6-05 x402 — STOP GATE

### P7 — FUTURE LAB (меню: F1–F11)
F1 Gasless ERC-4337 · F2 Digital twin · F3 Copilot · F4 Intent-engine · F5 Агент-экономика · F6 TEE/ZK · F7 x402 · F8 Councils · F9 A2A · F10 MPP · F11 zkML.
Рекомендованное комбо: **F3→F2→F1→F8→F5**. Внедрение — только по решению владельца.

---

## 📓 ЖУРНАЛ СЛАЙСОВ (append-only)

| # | Дата | Слайс | Коммит | Тесты | Примечание |
|---|---|---|---|---|---|
| 01 | 2026-09-16 | Лого-концепты KARTA (3 SVG) + RTM-синк | `dbf5de4` | — | 3 варианта: чакра/монограмма/щит |
| 02 | 2026-09-16 | Phase 0: AUDIT_REPORT + PROGRESS.md | `213a1bf` | 6/6 passed | 5 P0 подтверждены с file:line |
| 03 | 2026-09-18 | S0-03/S0-04: ARCHITECTURE_CURRENT + THREAT_MODEL + мега-PROGRESS | `f40b6c6` | 6/6 passed | P0 полностью закрыт |
| 04 | 2026-09-18 | S1-02 Argon2id + миграция legacy-хешей | `c0a6c97` | 14/14 passed | venv получил pytest+argon2-cffi |
| 05 | 2026-09-18 | S1-04 KeyVault lazy-init + guard-тесты | `7d24267` | 21/21 passed | core.py чист; executor retryable |
| 06 | 2026-09-18 | S1-05 Scoped approve (max заблокирован) | `f2bc393` | 27/27 passed | + revoke_approve; prompt LLM обновлён |
| 07 | 2026-09-18 | S1-09 Честный health | `1d8f00b` | 33/33 passed | live: degraded (rpc down, redis ok, gigachat) |
| 08 | 2026-09-18 | S1-06 Dharma Engine MVP | `fbdd352` | 65/65 passed | 15 правил, allow/deny/require_approval, гейт в обоих путях |
| 09 | 2026-09-18 | S1-08 Kill-switch drill | `82f7826` | 70/70 passed | soft/hard, терминальный, блок во всех путях |
| 10 | 2026-09-18 | S1-03 JWT: ротация refresh, reuse-detection, revoke-all, rate-limit | `b5c81f5` | 84/84 passed | tokens.py + ratelimit.py; RefreshStore in-memory (PG → S2) |
| 11 | 2026-09-18 | S1-07 Контракты: починена компиляция (4 бага), 56 контрактных тестов, CI Slither+Aderyn | `0746648` `cf2773f` `2881461` | 56 passing | до этого дня контракты не компилировались |

## 💡 ИДЕИ НА ОБСУЖДЕНИЕ (новое — предлагать после отчётов)

1. **ChainSight (crypto-mcp-server) как data-provider для KARTA** — два проекта композируются: ChainSight = intelligence (цены/газ/киты, уже готов: 148 тестов, envelope, rate-limit), KARTA = execution (policy/simulation/audit). Интеграция через MCP или REST — сильная синергия 1+1>2.
2. **Кросс-проектный перенос паттернов**: в ChainSight уже реализованы envelope, `/health`, rate-limit, RBAC, ключи `cms_`, MCP_TOOL_CONTRACTS — KARTA может заимствовать проверенный код/подходы вместо изобретения (экономия недель в P2/P3).
3. **Общий скилл-конвейер «SPEC→PROGRESS→слайс»** — зафиксировать в скилле удачные шаги обоих проектов (уже начато `spec-product-cycle`).

---

## 📦 ПРАВИЛА ДЛЯ ЭТОГО РЕПОЗИТОРИЯ

- **НЕ** коммитить `backend/.env`; секреты только `~/.env`/vault.
- **НЕ** трогать строки `MISTRAL*` в `~/.env` (даже при вычеркнутом провайдере).
- **НЕ** удалять файлы без подтверждения владельца.
- Перед каждым новым import: `pip show <package>`; в requirements.txt с версией; не выдумывать пакеты.
- Pydantic v2 (`model_validate`), type hints везде, никаких bare except.
- Push по правилам проекта (mrpkk-репозитории — сразу после коммита).
- Бэкап: локальный + GDrive (полный — в конце сессии).
- Obsidian: daily note каждый значимый шаг; проектные изменения — `2-projects/`.

## 🔗 КАРТА ДОКУМЕНТОВ

| Документ | Путь |
|---|---|
| Канон-спека | `~/Документы/work/projectBooks/OnChainKartaSPEC.md` |
| Эталон-промпт | `~/Документы/work/projectBooks/OnChain_AI_Agent_MODERNIZATION.md` |
| Книга проекта | `~/Документы/work/projectBooks/OnChain_AI_Agent.md` |
| Аудит | `docs/AUDIT_REPORT.md` · `docs/ARCHITECTURE_CURRENT.md` · `docs/THREAT_MODEL.md` |
| Лого | `branding/*.svg` |
| Парный проект | `~/crypto-mcp-server` (ChainSight v2, 148 тестов, ждёт STOP-01) |
