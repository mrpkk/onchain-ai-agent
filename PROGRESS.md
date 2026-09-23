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
8. **22.09.2026** — **лого K (монограмма) выбрано владельцем**; ассеты собраны и встроены (S4-09 ✅). **v2.0-alpha смержен в main** (тег `v2.0-alpha`, merge `4b8b7d3`).
9. **22.09.2026** — **бесплатные инструменты ≤1 ГБ — ставить/использовать без спроса** (правило владельца, записано в AGENTS.md); >1 ГБ или платное — спрашивать.
10. **22.09.2026** — **P6 «Агент-экономика» начат** по команде владельца («начинай, всё что в SPEC»); порядок по умолчанию S6-04 → S6-03 → S6-01 → S6-02 (старт не требует P5). **Āgama: публикация отложена** («продукт сырой — сначала тесты/доработка»).

## 🧭 ТЕКУЩИЙ ШАГ (обновлять при каждом слайсе)

**Статус:** **P0–P4 закрыты полностью** (P4 = 10/10 после S4-09; сверх плана закрыты S4-15 SAST/dep-audit, S4-16 docs-пакет, S4-17 ops-реконсиляция). **v2.0-alpha в main** (тег, merge `4b8b7d3`). Тесты: **235 backend + 56 контрактных** (вкл. coverage-гейт 80%, bandit medium+ = 0, pip-audit = 0). Live E2E: `scripts/e2e_live.py` 13/13.
**Инфраструктура P5 (22.09):** **RPC ✅ работает из РФ** — `ethereum-rpc.publicnode.com` (306ms, дефолт в settings), запас `eth.drpc.org`, `1rpc.io/eth`; health показывает `rpc: ok` (реальный блок mainnet). **Foundry ✅** установлен (forge/cast/anvil 1.8.1, up to date). **4337 — локальный EntryPoint** (решение владельца). **Sepolia-деплой** — ждёт решения владельца («зачем?» — объяснение в отчёте 22.09; вопрос «деплоим сейчас/после P5»).
**P6 идёт (23.09):** **S6-04 ✅ MCP-сервер** + **S6-03 ✅ Ricardian 2-of-3** (API+UI, anvil-цикл, live Sepolia #0) → дальше S6-01 ERC-8004 (local) → S6-02 Escrow (local). **P5:** S5-03 ✅ (Sepolia задеплоен); старт S5-04/S5-05 — по команде («запускай S5-04»).
**STOP-GATE (ранее 6) — ЗАКРЫТЫ все:** execution-граница = тиры 0–1 симуляция (реальное — P5); PG docker ✅; DeepSeek-ключ ✅; `backend/.env` выведен из контура ✅; фронтенд A ✅; футуристики — в P7 (по решению).

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
- [x] S4-01 Дизайн-система + статика (вариант A): токены SPEC §11 (`static/tokens.css`: цвета/типографика/8pt/радиусы/motion/тени + light-тема), UI вынесен из main.py в `static/` (index.html, dashboard.css на токенах, dashboard.js, manifest.webmanifest — PWA); `main.py` 1111→~650 строк (FileResponse + StaticFiles); заголовок дашборда — KARTA. 4 теста (root/static/manifest/id-связность). Коммит `87ce4dd`.
- [x] S4-02 Кокпит: топбар с WS-индикатором (LIVE/OFFLINE + автопереподключение), карточки агентов (статус-бейджи, start/stop/kill/heartbeat/цель/tx), статус-карточка (сеть, кошелёк, heartbeat), **лента решений** с confidence-баром, risk-бейджем и кнопкой **«Почему?»** (policy_verdict/флаги), **очередь undo** (отмена), **Sakshi Log** с раскрытием payload и хвостом hash, tx-drawer. WS-события live-обновляют список/ленту (agent.status/decision.proposed/action.scheduled). JS: XSS-safe (textContent),  чист; PnL/балансы — честный empty-state (источник данных в S5). Живая проверка: сервер на :8090 отдаёт кокпит (Лента решений/Sakshi/Очередь undo). Коммит `0029236`.
- [x] S4-03 Chat-first: `agent/intent.py` (pydantic `IntentSchema`: action/params/summary/confidence/assumptions/clarifications; парсер через LLM-роутер, prompt_version intent-1.0), API **POST /agents/{id}/intent** (NL→intent + **Dharma-превью** вердикта с честными warnings) и **/intent/confirm** (исполнение через runtime полного контура: policy→simulation→timelock→dispatch; 409 если агент не запущен; LLM-недоступность → 503). UI: панель «Чат-задача» в кокпите (ввод → карточка intent с params/confidence/policy-бейджем/допущениями → Подтвердить/Отмена → результат: confirmed tx_hash / failed reason / pending→undo-очередь). 9 тестов. Коммит `3b26f2d`.
- [x] S4-04 Онбординг + тиры: `runtime/tiers.py` (4 тира: Demo/Simulated/Limited/Full; шаблоны Dharma-политик; `tier_simulation_mode`: 0–1 = только симуляция, 2–3 = исполнение за гейтами). API: `tier` в AgentCreate/Response (**по умолчанию 0 Demo**), **авто-политика тира при создании агента** (create_agent), **POST /agents/{id}/tier** (смена тира → новая версия политики + WS). Фабрика: tier → simulation_mode + лимиты. UI: **мастер за 3 шага** (режим → шаблон задачи (газ/баланс/своя) → лимиты → «Запустить»), авто-открытие при нуле агентов, кнопка «Мастер». Живая проверка: tier=1 → per_tx 0.5; смена на tier=3 → policy v2 per_tx 1.0. 6 тестов. Коммит `38e3cc8`.
- [x] S4-05 Decision diary + «Почему?» (лента решений S4-02) **и approvals-inbox в кокпите**: панель «Подтверждения» (карточки с агентом/действием/params/reasoning, кнопки ✅/❌), живое обновление по WS `approval.requested`, тот же web-путь, что у Telegram (единый resolve). i18n-ключи RU/EN (+панель подтверждений). Коммит `6b26a66`.
- [x] S4-06 Telegram-approve: `integrations/telegram.py` (Bot API на httpx, inline-кнопки ✅/❌, `parse_callback`), `telegram_poller.py` (long-poll → **общий** `resolve_approval`), `runtime/approvals.py` (**единый путь web/TG**: одобрение → `runtime.execute_intent` → полный контур policy/sim/timelock — Telegram НЕ обходит policy), `ApprovalRepository` + API (`GET /approvals`, `POST /approvals/{id}/approve|reject` с ownership-изоляцией), ядро: requires_approval/ask_human → заявка + WS `approval.requested` + notifier; health: telegram configured/not_configured; lifespan запускает poller при наличии токена. **Конфиг:** `KARTA_TELEGRAM_BOT_TOKEN` + `KARTA_TELEGRAM_CHAT_ID` (fallback TG_USER_ID); токена нет → интеграция честно в disabled (создание бота — действие владельца через BotFather). 8 тестов (Bot API через MockTransport, poll-loop, сервис, API-флоу, core-тик). Коммит `78b7c30`.
- [x] S4-07 Отчёты: `runtime/reports.py` — честная сводка (`decisions_count`, транзакции/confirmed, **газ из реальных полей** в ETH, `pnl_available=False` + причина «нет сделок/цен (Phase 5)» — никаких выдуманных PnL) и CSV-билдеры; API **GET /agents/{id}/reports/summary** и **GET /agents/{id}/export.csv?dataset=decisions|transactions|audit** (audit — через Sakshi export_csv, attachment). UI: панель «Отчёты» (сводка + 3 кнопки CSV-скачивания через fetch+blob). 6 тестов. Коммит `fe39db9`. Долг: расчёт PnL (cost basis/цены) — при появлении исполнения и ценового оракула.
- [x] S4-08 i18n RU/EN: `static/i18n.js` (два словаря ~130 ключей, `t()` c подстановками, переключатель в топбаре, persist `karta_lang`, автодетект языка; архитектура расширяема DE/ES/FR/ZH), вся разметка через **data-i18n/data-i18n-placeholder**, JS-строки переведены на ключи, `onLangChanged` перерисовывает динамику; тест **паритета ключей RU==EN**. Landing/docs: README = код (S2-08), Swagger /docs, экран входа — точка входа; отдельный маркетинговый лендинг — при публикации (STOP-GATE бренда). Коммит `41eb781`.
- [x] S4-09 KARTA-ассеты: **выбрано владельцем 22.09 — лого K (монограмма)**: PNG-набор (16/32/48/180/512 + apple-touch + OG 1200×630) в `branding/out/`, встроен в кокпит (`static/icons/`: favicon, apple-touch, og-теги) и PWA-манифест (иконки 5 размеров); 2 новых теста (ассеты отдаются, манифест объявляет). Коммит `38dcf8c`. **P4 закрыта 10/10.**
- [x] S4-10 Дифференциаторы (реализовано 2 ключевых): **Intent→Guarantee** — `agent/policy_intent.py` (NL-правило → pydantic-патч → merge с активной политикой → валидация Dharma → YAML-превью; применение ТОЛЬКО через явный PUT с новой версией) + API `POST /agents/{id}/policy/from-text` + панель «Правила (Dharma)» в кокпите; **Agent Health Score** — `runtime/health_score.py` (penalty из policy-отказов/провальных решений/доли провальных tx; band healthy/degraded/critical + рекомендация — совет, не автомат), встроен в reports/summary + строка «Здоровье» в UI. Остальные (Counterfactual/Drift/Ladder/Replay/Policy Simulator) — зафиксированы как кандидаты P7 (после появления исполнения данные станут полнее). 10 тестов. Коммит `061bee6`.

- [x] S4-11 Policy Simulator: `runtime/policy_simulator.py` — прогон последних решений через текущую и кандидатную политики → изменения вердиктов (tightened/relaxed/unchanged) БЕЗ применения; API `POST /agents/{id}/policy/simulate` + кнопка «Симулировать» в панели правил (impact-превью до «Применить»). 4 теста.
- [x] S4-12 Trust Ladder: `tiers.trust_ladder_rung()` (observe→suggest→simulate→approve→limited_auto→autonomous; консервативный маппинг tier+undo/approvals) → в `reports/summary.trust` + строка «Автономия» в UI. 2 теста. Коммит `5014142`.

- [x] S4-13 Autonomy Drift Detection: `runtime/drift.py` — сравнение окон истории (средняя сумма, новые типы действий, рост high/critical-риска) → сигналы + drift_score/level (stable/watch/drift); API `GET /agents/{id}/drift` + строка «Дрейф» с сигналами в отчётах. 3 теста.
- [x] S4-14 Decision Replay v1: `runtime/replay.py` — восстановление решения + вердикт **текущей** политики vs сохранённого (`verdict_changed`); API `GET /decisions/{id}` (ownership) + кнопка «Переиграть» в карточке решения. 2 теста. Коммит `30e7381`.
- [x] S4-15 SAST + dep-audit (секьюрити-долг P1): **bandit medium+ = 0 находок** — GigaChat переведён с `verify=False` на CA-бандл **НУЦ Минцифры** (`backend/src/security/certs/russian_trusted_root_ca.pem`, env-override `GIGACHAT_CA_BUNDLE`, честный warning-fallback), `settings.host` дефолт → `127.0.0.1` (деплой переопределяет: Dockerfile `--host 0.0.0.0`); **pip-audit = 0 уязвимостей** — миграция `python-jose`→**PyJWT 2.14** (у python-jose транзитивный `ecdsa` с PYSEC-2026-1325 без фикса; PyJWT на `cryptography`, HS256-путь без изменений API токенов). CI: шаги **bandit (medium+, strict)** + **pip-audit (strict)**. Живой регресс: **E2E v2** (13 проверок — live GigaChat policy from-text, intent, WS, decisions, drift, replay, summary, CSV, approvals, Sakshi-цепочка) — всё зелёное; JWT после миграции проверен на живом сервере. 218/218. Коммит `51d8e73`.
- [x] S4-16 Docs-пакет (SPEC-деливераблы): `docs/SECURITY.md` (as-built posture: секреты/аутентификация/Dharma/Sakshi/LLM-TLS/контракты/CI-таблица/честные ограничения), `docs/ARCHITECTURE.md` (as-built: слои, поток решения, тиры, данные, инфра, со ссылками на AUDIT/THREAT/API), `docs/API.md` — **авто-генератор** `docs/generate_api_md.py` из OpenAPI (37 роутов; перегенерировать после изменения роутов). Проверкой найден и исправлен **баг compose**: `backend` зависел от `redis` (profile optional) → `docker compose up` падал; теперь dev-профиль = postgres+backend, redis только с `--profile optional` (валидировано `docker compose config`). Коммит `c3b6f7b`.
- [x] S4-17 Ops-честность + воспроизводимость: **реконсиляция при старте** — `runtime/reconciliation.py` (running-агенты после падения/рестарта процесса → stopped без автовозобновления; hook в `_lifespan`; закрыт долг S3-04 «внешний watchdog» в его in-repo части: процесс не может «возобновить» неподтверждённое исполнение); **coverage-гейт 80%** в CI (факт 84%); **`scripts/e2e_live.py`** — 13-проверочный live-смоук, теперь в репо (env-конфиг `KARTA_E2E_*`); README синхронизирован (37 роутов, 221 тест, архитектурная схема as-built). Коммиты `58fcfe6` `c5ced6d`. Тесты: **221** (218 + 3 реконсиляции), полный прогон + live-смоук — зелёные.

### P5 — Исполнение 2.0

> **P5-ПЛАН К ОБСУЖДЕНИЮ (ИСПОЛНЕНИЕ ТОЛЬКО ПО ОТДЕЛЬНОЙ КОМАНДЕ — STOP-GATE).**
>
> **Предусловия (инфраструктура) — ОБНОВЛЕНО 22.09:**
> 1. **Рабочий RPC ✅ РЕШЕНО (бесплатно, проверено из РФ):** `ethereum-rpc.publicnode.com` (306ms; дефолт в `settings.py`), запас: `eth.drpc.org` (270ms), `1rpc.io/eth` (501ms); Sepolia: `ethereum-sepolia-rpc.publicnode.com` (322ms), `1rpc.io/sepolia`. Health: `rpc: ok` (блок mainnet читается). Ankr/LlamaRPC из РФ не работают (ключ/SSL).
> 2. **Foundry ✅ УСТАНОВЛЕН** (владелец разрешил 22.09): forge/cast/anvil 1.8.1 в `~/.foundry/bin`, up to date.
> 3. **Бюджет тестов:** real-money нет; Sepolia-краник бесплатно (Google Cloud ~0.05 ETH/24ч — требует 0.001 ETH mainnet; PoW-кран pk910 — без требований; Alchemy 0.1 ETH/день — требует 0.001 mainnet).
> 4. **4337:** только локальный EntryPoint (решение владельца 22.09); bundler/paymaster платные — не используем.
> 5. **Sepolia-деплой ✅ ВЫПОЛНЕН 23.09** — кошелёк владельца, 4 контракта + live-смоук (см. S5-03 ниже); баланс после: 0.1540 ETH. Краны: без mainnet-баланса из РФ реально работает только PoW `sepolia-faucet.pk910.de` (майнинг в браузере; при нужде — автоматизирую через headless Thorium); Google/Alchemy/Infura/Chainlink требуют 0.001 ETH mainnet.
>
> **Смета (соло+AI):** S5-04 EIP-1559 — 1 дн · S5-05 private RPC — 1 дн · S5-07 multi-chain (+Base) — 2–3 дн · S5-01 swap (агрегатор+slippage-guard) — 3–4 дн · S5-02 bridge — 2–3 дн · S5-06 ERC-4337 (session keys по готовой таблице; bundler/paymaster платные → локальный EntryPoint в тестах) — 4–6 дн · S5-03 deploy Sepolia — 1–2 дн (отдельная команда). **Итого ≈ 3–4 недели.**
>
> **Порядок по умолчанию:** S5-04 → S5-05 → S5-07 → S5-01 → S5-02 → S5-06 → S5-03.
>
> **Вопросы владельцу — ОТВЕТЫ 22.09:** (1) RPC — ✅ бесплатные РФ-доступные (проверены живьём, дефолт PublicNode); (2) Foundry — ✅ ставим (установлен 1.8.1); (3) 4337 — ✅ только локальный EntryPoint; (4) Sepolia — вопрос «зачем» задан владельцем, объяснение дано; **ждёт: деплоим сейчас / после кода P5**. Старт P5 — по команде («запускай P5»/«запускай S5-04»).

- [x] S5-03 Deploy Sepolia: **выполнено 23.09 кошельком владельца** (`WALLET_METAMASK_ETH_ERC20`), RPC PublicNode. **AgentRegistry** `0x773945A9eA400e9c8704a2c02AAAbF449cFc20E5` · **Escrow** (арбитр=деплоер, тестнет) `0xB73c9F99d40116501C0a18c4019Ac8E91ED7dE8a` · **RicardianAgreement** `0x153010a3f18cf363A87364BB8182Fc13ABF95dF2` · **MockERC20 (mUSDC)** `0x212774d426519437d5Eb1126fE382fC7b7cCe7B0`. **Live-смоук**: `registerAgent` tx `0x372abb…54bcda` (block 11762219, status 1, agentId 0, событие AgentRegistered). Запись: `smart-contracts/deployments/sepolia.json`. Расход: ≈0.0033 ETH (баланс 0.1540). Коммит `d14fea9`.
- [ ] S5-01 Swap (1inch/агрегатор + slippage-guard) · S5-02 Bridge
- [ ] S5-04 EIP-1559 + газ-оракул · S5-05 Private RPC (Flashbots-класс) + jitter
- [ ] S5-06 ERC-4337: smart account + session keys (TTL, revoke) + paymaster + social recovery
- [ ] S5-07 Multi-chain adapter (сеть = config {rpc[], explorer, finality, health})

### P6 — Агент-экономика (по решению)

> **СТАТУС 22.09: НАЧАТ по команде владельца («начинай, всё что в SPEC»).** Порядок: S6-04 → S6-03 → S6-01(local) → S6-02(local) → on-chain часть после P5 → S6-05 (решение).
>
> **P6-ПЛАН (исполнение — по слайсам, канон SPEC).**
>
> **Что уже есть:** контракты `AgentRegistry` / `Escrow` / `RicardianAgreement` (компилируются, 56 тестов, Slither+Aderyn в CI); Sakshi-аудит; Dharma-гейты; кокпит; approvals-путь.
> **Предусловия:** S6-01/S6-02 в on-chain части требуют P5 (реальное исполнение; иначе — только локальные devnets); S6-04 (MCP наружу) — сетевая точка присутствия (домен/порт) и решение о том, кому открывать; S6-05 x402 — STOP GATE (приём крипто-платежей).
>
> **Смета (соло+AI):** S6-04 MCP-сервер наружу (tools: policy/decisions/audit/reports; auth по API-ключам `karta_`) — 2–3 дн · S6-03 Ricardian 2-of-3 UI (локальный hardhat) — 3–4 дн · S6-01 ERC-8004 (регистрация агента + бейджи; локально → Sepolia после P5) — 3–4 дн · S6-02 аренда через Escrow (депозит/расчёт/спор) — 4–6 дн · S6-05 x402 — отдельное решение. **Итого ≈ 2–3 недели (без S6-05).**
>
> **Порядок по умолчанию (старт не требует P5):** S6-04 → S6-03 → S6-01(local) → S6-02(local) → S6-01/S6-02(Sepolia — после P5) → S6-05(решение).
>
> **Вопросы владельцу:** (1) начинать P6 до P5 или после? (2) S6-04: KARTA как MCP-сервер наружу — кому (партнёрам/публично) и где (локально/VPS)? (3) Ricardian 2-of-3: кто третий арбитр (владелец/сервис)? (4) x402 — рассматривать вообще?

- [x] S6-04 MCP-сервер наружу (v1, local-first): **streamable HTTP (stateless) на `POST /mcp`** — `backend/src/mcp/` (`contracts.py` — pinned-контракты 8 read-tools + gated write; `server.py` — MCPServer 2.0 + `MCPDispatcher` со свежим app на lifespan). Auth: `Authorization: Bearer karta_…` в каждом вызове (через `Context.headers`) → строгий owner-scope. **API-ключи `karta_`**: SHA-256 в `api_keys` (миграция `0003`: name/prefix), эндпоинты `POST/GET/DELETE /api/v1/api-keys` (скоупы `mcp:read/mcp:write`, ownership-изоляция). **READ-tools (SPEC §10):** `get_wallet` · `get_balance` · `get_gas` · `get_portfolio` (честно: токены — Phase 5) · `get_transactions` · `agent_status` (health/trust/drift) · `audit_log` (Sakshi) · `get_decision` (Replay). **WRITE — gated, не зарегистрированы** (тест). OWASP MCP: pinned definitions + parity-тест, owner-изоляция, Host-allowlist `KARTA_MCP_ALLOWED_HOSTS`, структурированные ошибки. Docs: `docs/MCP.md` (Claude/Cursor/OpenCode) + `docs/MCP_TOOL_CONTRACTS.md` (генератор + parity). Живая проверка на :8090 (tools/list + agent_status с реальным health/trust/drift). 10 тестов. Коммит `cc59f7e`. Долг: rate-limit MCP (SPEC: write 10/мин) — при включении write.
- [x] S6-03 Ricardian 2-of-3 UI: `integrations/ricardian.py` (тестнет-only guard: Sepolia/anvil, симуляция до отправки, honest-ошибки: SIMULATION_REVERT/MAINNET_FORBIDDEN/SIGNER_MISSING), API `/api/v1/ricardian/*` (wallet/list/detail/create/sign/execute/dispute, JWT), **панель «Соглашения» в кокпите** (создание, карточки со статусом/подписями/вехами, действия Подписать/Выполнить/Спор; i18n RU/EN). **Anvil-интеграция полного цикла**: create→B+C подписи→active→эскроу→execute→completed+выплата (`scripts/ricardian_anvil_flow.py` — УСПЕХ). **Live Sepolia**: соглашение #0 создано через API (tx `03947a…`, block 11766276, 3 стороны, 1 веха) + fund-механика. 10 тестов. Коммит `d517a7f`. Долг: Ricardian-«агентская» интеграция (агент как сторона) — после P5-исполнения.
- [ ] S6-01 ERC-8004 live + бейджи · S6-02 Аренда через Escrow · S6-05 x402 — STOP GATE

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
| 21 | 2026-09-18 | S4-01…S4-14 Friendly-ядро (кокпит, чат-first, тиры, approvals+TG, отчёты, i18n, 6 дифференциаторов) | `87ce4dd`..`30e7381` | 218/218 backend + 56 контрактов | E2E v2 live зелёный; P4 9/10 (S4-09 ждёт лого) |
| 22 | 2026-09-18 | S4-15 SAST/dep-audit (CA НУЦ, PyJWT, CI bandit+pip-audit) | `51d8e73` | 218/218 | bandit medium+ 0 · pip-audit 0 |
| 23 | 2026-09-18 | S4-16 Docs-пакет (SECURITY/ARCHITECTURE/API + генератор) + fix compose redis-profile | `c3b6f7b` | 218/218 | API.md авто-генерация; compose валидирован |
| 24 | 2026-09-18 | S4-17 Реконсиляция при старте + coverage-гейт + e2e_live.py в репо + README-синк | `58fcfe6` `c5ced6d` | 221/221 + live-смоук 13/13 | честные состояния после падения процесса |
| 25 | 2026-09-22 | **Мерж v2.0-alpha в main** (тег, merge `4b8b7d3`) + **S4-09 лого K** (ассеты+кокпит+манифест, `38dcf8c`) | `4b8b7d3` `38dcf8c` | 235/235 | P4 закрыта 10/10; выбор лого владельцем |
| 26 | 2026-09-22 | Инфра P5: **RPC из РФ проверен** (publicnode/drpc/1rpc; дефолт обновлён) + **Foundry 1.8.1** + `TG_KARTA_BOT`-алиас + правило ≤1ГБ | `1760a97` | 225/225 + health rpc:ok | health: rpc ok (блок mainnet) |
| 27 | 2026-09-23 | **S5-03 Деплой Sepolia** — 4 контракта + live registerAgent (status 1, agentId 0); `deployments/sepolia.json`; deploy.js пишет tx-хэши | `d14fea9` | 56 контрактных (локально) + live | баланс 0.1540 ETH; арбитр Escrow = деплоер (тестнет) |
| 28 | 2026-09-23 | **S6-04 MCP-сервер** (streamable HTTP read-only 8 tools) + API-ключи `karta_` + docs/контракты | `cc59f7e` | 235/235 + live MCP | P6 пошёл; write-tools gated |
| 29 | 2026-09-23 | **S6-03 Ricardian 2-of-3**: сервис+API+UI-панель; anvil полный цикл; live Sepolia create | `d517a7f` | 245/245 + live | escrow-механика, тестнет-only guard |

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
| Доки (as-built) | `docs/SECURITY.md` · `docs/ARCHITECTURE.md` · `docs/API.md` (генератор `docs/generate_api_md.py`) |
| Лого | `branding/*.svg` |
| Парный проект | `~/crypto-mcp-server` (ChainSight v2, 148 тестов, ждёт STOP-01) |
