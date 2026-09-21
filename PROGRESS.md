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

**Статус:** P0 закрыт 100%; **P1 «Безопасность» — ЗАКРЫТА 9/9** (S1-01 секреты+CI · S1-02 Argon2id · S1-03 JWT · S1-04 KeyVault · S1-05 approve · S1-06 Dharma · S1-07 контракты+CI · S1-08 kill-drill · S1-09 health) (S1-02 · S1-04 · S1-05 · S1-06 · S1-08 · S1-09 · S1-03 · S1-07). Тесты: **140 зелёных** (backend 84 + контракты 56). Раннеры: `backend/.venv/bin/python -m pytest` и `npx hardhat test` (smart-contracts).
**Следом (P3, по команде):** S3-01 ✅ → S3-02 Simulation-гейт (eth_call + anvil когда доступен), S3-03 timelock/undo, S3-04 dead-man switch, S3-05 Guardian. **P2 закрыта 8/8.** Прежний план: S2-01 ✅ → далее S2-02 Sakshi Log (HMAC-цепочка, запись каждого решения в `audit_events`), S2-03 WS-события, S2-05 LLMProvider+structured output, S2-07 Mempool real/NOT_IMPLEMENTED, S2-08 README=код. Плюс долг: RefreshStore → таблица `refresh_tokens` (сейчас in-memory), decision-diary запись в `decisions` (таблица готова).
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
- [x] S1-01 Секреты: `backend/.env` выведен из контура (переименован в `.env.migrated-20260918`, chmod 600; в git не попадает — паттерн `.env.migrated-*`). Владелец: Mistral-ключи без ценности (заблокирован в РФ) — не переносим; цепочка LLM: GigaChat → запасные → OpenCode Zen (крайний случай). Смоук из `backend/` без .env: `db: ok`, `llm: gigachat`, register 201. CI: gitleaks + grep-скан приватников. Коммит `b077612`.
- [x] S1-02 Argon2id (passlib) + миграция legacy sha256 при логине + 8 тестов — `c0a6c97`
- [x] S1-03 JWT-пара: `security/tokens.py` (access 15м + refresh 7д, type-claim, jti, family_id), ротация на каждом refresh, reuse-detection → отзыв всей семьи, эндпоинты `/auth/refresh` · `/auth/logout` · `/auth/revoke-all`, rate-limit логина 5/мин/IP (`api/ratelimit.py`), 14 тестов (unit+API) — `b5c81f5`. RefreshStore пока in-memory — PG-персистентность в S2-01.
- [x] S1-04 KeyVault-миграция: lazy `_ensure_wallet()`, guard-тест + поведенческие тесты (executor retry при RPC) — `7d24267`
- [x] S1-05 Scoped approve: `_to_approve_amount` блокирует None/negative/max, `revoke_approve`, amount-паспорт из решений/планов — `f2bc393`
- [x] S1-06 Dharma MVP: `security/dharma/` (dsl/compiler/ctx/evaluator), 15 правил, гейт в обоих путях, negative-тесты, `DHARMA_ENFORCE=off` — `fbdd352`
- [x] S1-07 Контракты: **обнаружено, что контракты не компилировались вовсе**; исправлены 4 класса дефектов: (1) `bool ok = safeTransfer` ×5 — OZ v5 возвращает void; (2) коллизия `error MilestoneDisputed` ↔ `event MilestoneDisputed` (твердый запрет Solidity); (3) `signers` смешивал членство и подпись — ВСЕ участники помечались «уже подписавшими», активация 2-of-3 была **невозможна** → разделены `members`/`signers`; (4) guard дубликата имени `nameToAgentId != 0` не ловил id=0 → `_nameUsed`. Добавлены `contracts/mocks/MockERC20.sol`, тесты Escrow (17) + Ricardian (22) + AgentRegistry (17) = **56 зелёных**; CI: backend-сьют + `npx hardhat test` + Slither (`fail-on: high`) + Aderyn (soft — калибровка на subdir) — `0746648` + `cf2773f` + `2881461`
- [x] S1-08 Kill-switch drill: `trigger_kill_switch(soft/hard)`, блок исполнения во всех путях, терминальный hard (без auto-resume), 5 тестов — `82f7826`
- [x] S1-09 Честный `/health` + `/health/deep`: реальные TCP/RPC/LLM/KeyVault, статусы ok/degraded/down — `1d8f00b`

### P2 — Честный фундамент
- [x] S2-01 PostgreSQL: 14 таблиц (SPEC §6.1) в `backend/src/db/models.py` (кросс-диалектные UUID/JSON: PG-JSONB ↔ SQLite), async engine/session + `session_scope()` (`db/database.py`), репозитории User/Agent/Transaction (`db/repositories.py`), Alembic (async env, миграция `17e2466e8f71` применена на живой PG). API переведён с in-memory dict'ов на репозитории (users/agents/transactions; health считает running из БД). Тесты: **3 персистентности** («рестарт» = reset_engine → данные живы) на SQLite + смоук на реальном PG (register→login→create→list, строки в таблицах подтверждены psql). Dev-PG: docker-контейнер `karta-postgres` (порт **5433**, agent/agent, volume `karta_pgdata`); compose-порты выровнены (PG 5433, Redis 6380 — системные 5432/6379 заняты). Коммиты `e33fc7a` `685eb00` `e3576d9` `8a2d65a`.
- [x] S2-02 Sakshi Log + Decision Diary: `security/sakshi.py` (HMAC-цепочка `hash_n = HMAC-SHA256(audit_key, prev_hash‖canonical(payload))`, `verify_chain` ловит подмену), `DecisionRepository` (тезис ДО: action/reasoning/confidence/risk/policy_verdict), интеграция в core (`_persist_decision`, `_sakshi_append` в `_tick` и у policy-вердиктов; активируется при `db_agent_id`+`sakshi`), экспорт-CLI `scripts/karta_audit_export.py --format json|csv`, PG-триггер append-only (миграция `0002`, проверен тестом: UPDATE заблокирован). 7 тестов, включая PG-триггер и tamper-detection. Коммит `6395865`. Долг: запись kill-switch/step-событий из sync-контекста — при подключении runtime к API (S2-03+).
- [x] S2-03 WebSocket `/ws?token=<access-JWT>`: `api/ws.py` (ConnectionManager, auth по decode_token, hello-фрейм, 4401 при невалидном токене), broadcast `agent.status` из API (start/stop/kill), `event_sink` в ядре (decision.proposed; ошибки sink не ломают агента), 5 тестов (валидный/невалидный токен, hello, fan-out на 2 клиента, sink-emit, устойчивость к падению sink). Бонус: `Settings` теперь `extra=ignore` — приложение не падает от чужих ключей мастер-`~/.env` (при запуске с CWD=$HOME). Коммит `d433748`.
- [x] S2-04 Redis — решение: **NOT_REQUIRED для одно-процессного v2** (WS fan-out — in-process ConnectionManager; rate-limit — in-memory SlidingWindowLimiter; кэш цен — TTL в perception). Redis остаётся кандидатом для multi-worker (WS pub/sub, общий rate-limit) — сервис в compose переведён в профиль `optional` (`docker compose --profile optional up`). Health остаётся честным (системный Redis на 6379 отображается ok; если Redis нужен — поднимаем из профиля).
- [x] S2-05 LLMProvider-цепочка: пакет `providers/llm/` — `base.py` (LLMProvider/LLMResult/ProviderError с retryable-классификацией), `gigachat.py` (OAuth + кэш токена + 401-инвалидация), `openai_compat.py` (DeepSeek/Qwen/агрегаторы/Ollama, маппинг HTTP 429/5xx→retryable), `router.py` (fallback по цепочке **GigaChat→DeepSeek→Qwen→агрегатор→Ollama**, circuit breaker 3×60с, repair-попытка при invalid JSON, `extract_json` из ```-блоков). `reasoning.py` переведён на роутер: pydantic `AgentDecisionSchema` (Literal-поля, confidence 0..1) → `AgentDecision`; полный отказ → fail-safe `ask_human` (critical). Сборка цепочки из env: `build_default_router()` (проверено: `['gigachat','deepseek']`). Трейсинг-lite: provider/model/latency/tokens в `LLMResult` + структурный лог решения. 11 тестов (fallback, repair, breaker, HTTP-маппинг, GigaChat-кэш токена, fail-safe). Коммит `5592952`. Остаток S2-06: request_id/agent_id/cost/prompt-version.
- [x] S2-06 Трейсинг решений: `observability/tracer.py` — `new_request_id`, структурный JSON-лог `llm_trace` (request_id/agent_id/provider/model/latency/tokens/prompt_version/ok), `estimate_cost` из env-прайса `KARTA_PRICE_<PROVIDER>_IN/OUT` (нет цен → None — не выдумываем). Роутер генерит request_id на каждый вызов и трейсит success/полный отказ; `LLMResult.request_id/cost_usd`; `PROMPT_VERSION="1.0"`; agent_id прокинут из ядра через `LLMReasoner`. 6 тестов. Коммит `83e5d88`.
- [x] S2-07 MempoolMonitor: **реальный** сканер блоков — watch-фильтр адресов (from/to), газ-тренд по baseFee (up/down/flat), история, `scan_once` c честным `rpc_unavailable`, `status()` для capabilities. Фейковый/битый цикл (`range(bool and len())`) заменён. 6 тестов на fake-w3. Коммит `24b83bd`.
- [x] S2-08 README = код: честный ре-райт (18 маршрутов + WS сверены с приложением; статусы фич «работает/нет»; quickstart с PG 5433 + Alembic; env-таблица; тесты 116+56; архитектурная схема; дисклеймер). Коммит `ccafcd0`.

### P3 — Policy и Simulation
- [x] S3-01 Dharma-DSL в API: `PolicyRepository` (версии, одна активная; новая версия деактивирует прежнюю), эндпоинты **GET/PUT /api/v1/agents/{id}/policy** (валидация через `compile_yaml`, PolicyError→422, compiled-снимок в БД) и **POST /api/v1/policies/validate** ({valid, errors, window}); ownership-изоляция (чужой агент → 404). 6 тестов. Плюс тест-инфра-фикс: conftest сбрасывает `_login_limiter`/`_refresh_store` между тестами (иначе cumulative 429). Коммит `741a84d`. UI-редактор политик — в P4 (Кокпит).
- [x] S3-02 Simulation-гейт: `agent/simulation/service.py` — `SimulationReceipt(ok, engine, gas_estimate, revert_reason, state_diff, warnings, fork_block, ttl=120с)` + `is_fresh()`; движок **eth_call + estimate_gas** (revert → ok=False с причиной; estimate-фейл → ok=False). Гейт в ОБОИХ путях ядра (после policy, до dispatch): недоступна симуляция → блок «SIMULATION FIRST»; stale receipt → блок; успех → `simulation_passed` (audit+sakshi) и `state.last_simulation`. Anvil-fork — адаптер на будущее: `anvil_available()` честно сообщает, warnings пишут текущий движок. 9 тестов (service+freshness+гейт+spy-executor+tx-маппинг). Коммит `7ddcb60`.
- [x] S3-03 Timelock/undo-window: DSL-секция `undo: {window_seconds, threshold_eth}` (0 = выключено); `agent/timelock.py` — `TimelockQueue`/`PendingAction` (schedule/cancel/due/mark); гейт в decision-пути: сумма ≥ threshold → действие **откладывается** (`TxStatus.PENDING`, статус `awaiting_undo`, audit+sakshi+WS `action.scheduled`); `_process_due_actions()` в тике исполняет по сроку — **заново через полный контур** policy→simulation (skip_timelock); отмена `cancel_pending()`; kill-switch блокирует исполнение due. 7 тестов. Долг: plan-step путь — без timelock (MVP); API-эндпоинт отмены — в слайсе интеграции API⟷runtime. Коммит `3983e76`.
- [x] S3-04 Dead-man switch: `AgentConfig.deadman_timeout_seconds` (0=выкл), `heartbeat()` продлевает, `_check_deadman()` в начале тика: просрочка → **hard kill** без auto-resume (audit `deadman_triggered`). 4 теста. Коммит `aabaa4e`. Долг: внешний watchdog для случая смерти процесса (in-process не видит мёртвый процесс) — в слайсе эксплуатации/интеграции.
- [x] S3-05 Approval Guardian: `agent/guardian.py` — `AllowanceReport`, классификация (блок-лист spender → HIGH_RISK; 2^256-1 → HIGH_RISK; ≥ review_threshold → REVIEW; 0 → SAFE; ошибка чтения → REVIEW честно), `scan(w3, owner, pairs)`, `build_revoke_plan()` (только REVIEW/HIGH_RISK). 5 тестов. Честное ограничение: полное перечисление approvals невозможно без индексатора — сканируются известные пары. UI-рекомендации — в P4. Коммит `8bdb88f`.

- [x] S3-06 (интеграция, долги): **API⟷Runtime** — `runtime/factory.py` (сборка OnChainAgent из БД: активная политика DSL→CompiledPolicy, KeyVault, Sakshi, WS-sink, db_agent_id; нет политики→дефолт; нет vault/audit-ключа→честный режим без исполнения), `runtime/manager.py` (реестр running-агентов + asyncio-задачи). API: start→сборка+запуск, stop→остановка, kill-switch→hard kill runtime; новые эндпоинты **POST /heartbeat**, **GET /pending**, **POST /pending/{id}/cancel**, **GET /decisions** (Decision Diary из БД), **GET /audit** (Sakshi с hash-цепочкой). 9 тестов (fake-runtime + реальная фабрика с policy/дефолтом). Коммит `6fb6bd6`. Закрыты долги: heartbeat-API, cancel-API, decisions-API, audit-API, сборка из БД.

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
| 12 | 2026-09-18 | S2-01 PostgreSQL+Alembic+repositories, API на БД | `e33fc7a`..`8a2d65a` | 87/87 backend + PG smoke | 14 таблиц; dev-PG docker на 5433; «рестарт» не теряет данные |
| 13 | 2026-09-18 | S1-01 секреты: вывод backend/.env из контура + gitleaks CI | `b077612` | 87/87 | **P1 закрыта 9/9**; Mistral-ключи списаны владельцем |
| 14 | 2026-09-18 | S2-02 Sakshi Log: HMAC-аудит + Decision Diary + export + PG-триггер | `6395865` | 94/94 (вкл. PG-триггер) | запись активируется через `db_agent_id`+`sakshi` |
| 15 | 2026-09-18 | S2-03 WebSocket live-events + core event_sink + Settings.extra=ignore | `d433748` | 99/99 | fan-out на несколько клиентов; decision.proposed из ядра |
| 16 | 2026-09-18 | S2-05 LLMProvider-цепочка + structured output + breaker | `5592952` | 110/110 | chain=[gigachat,deepseek]; repair/breaker покрыты тестами |
| 17 | 2026-09-18 | S2-07 Mempool: реальный сканер + газ-тренд + честный rpc_unavailable | `24b83bd` | 116/116 | битый цикл заменён |
| 18 | 2026-09-18 | S2-08 README=код (сверен с роутами приложения) | `ccafcd0` | 116/116 | P2 закрыта 7/8 (+S2-06 частично) |
| 19 | 2026-09-18 | S2-06 Трейсинг llm_trace (request_id/agent_id/cost/prompt-version) | `83e5d88` | 122/122 | **P2 ЗАКРЫТА 8/8** |
| 20 | 2026-09-18 | S3-01 Policy API: версии DSL, validate, ownership | `741a84d` | 128/128 | P3 открыта (1/5) |

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
