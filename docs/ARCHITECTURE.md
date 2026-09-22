# KARTA — Architecture (as-built)

> Целевая архитектура в состоянии «реализовано» (P0–P4 закрыты). Историческая точка — [ARCHITECTURE_CURRENT.md](ARCHITECTURE_CURRENT.md).

## 1. Слои

```
┌─ UI: server-rendered кокпит (variant A) ───────────── backend/src/api/static/
│    tokens.css · dashboard.css/js · i18n.js (RU/EN) · manifest (PWA)
├─ API: FastAPI ─────────────────────────────────────── backend/src/api/main.py
│    auth · agents · policy · intent · approvals · reports · export · WS /ws
├─ Runtime ──────────────────────────────────────────── backend/src/runtime/
│    factory (сборка из БД) · manager (реестр задач) · approvals · reports
│    policy_simulator · drift · replay · health_score · tiers
├─ Agent core (Karma Engine) ────────────────────────── backend/src/agent/
│    core (loop, event_sink) · perception · reasoning · planning · execution
│    simulation · timelock · guardian · policy_intent · intent
├─ Security (Dharma/Sakshi/KeyVault) ────────────────── backend/src/security/
│    dharma (DSL→CompiledPolicy) · sakshi (HMAC-аудит) · keyvault · tokens · passwords
├─ Integrations ─────────────────────────────────────── backend/src/integrations/
│    telegram (Bot API) · telegram_poller (long-poll → единый resolve_approval)
├─ LLM ──────────────────────────────────────────────── backend/src/providers/llm/
│    base/router · gigachat (CA НУЦ) · openai_compat (DeepSeek/Qwen/агрегаторы)
├─ Data ─────────────────────────────────────────────── backend/src/db/ (PG + Alembic, 14 таблиц)
└─ Observability ────────────────────────────────────── backend/src/observability/tracer.py (llm_trace)
```

## 2. Поток решения

```
тик/чат/таймер
  → Perception (баланс/газ/мемпул, честный rpc_unavailable)
    → Reasoning (LLM-цепочка → план решения, prompt_version)
      → Planning (intent/params)
        → Dharma evaluate(decision) ── deny → Decision Diary (hold/deny)
                                     ├─ require_approval → approval (web+TG) → resolve
                                     └─ allow
          → Simulation (симуляция до отправки; receipt в решении)
            → Timelock (окно undo; отмена из «Очереди undo»)
              → Execution (подпись в KeyVault-слое, dispatch)
                → Sakshi (HMAC-запись каждого шага) + WS (live-события в кокпит)
```

Каждый шаг оставляет след: `decisions` (Decision Diary) → Sakshi → отчёты/CSV → Drift/Replay/Health.

## 3. Тиры и автономия

| Тир | Режим | Поведение |
|---|---|---|
| 0 Demo | симуляция | шаблонные задачи, всё в отчёт |
| 1 Simulated | симуляция | чат-задачи, intent, полный контур без dispatch |
| 2 Limited | исполнение | гейты: approvals, timelock, лимиты |
| 3 Full | исполнение | расширенные лимиты, undo-окно |

Trust Ladder: `observe → suggest → simulate → approve → limited_auto → autonomous` (консервативный маппинг в `runtime/tiers.py`).

## 4. Данные

PG (docker `karta-postgres` :5433 dev / compose в деплое) + Alembic. Ключевые таблицы: `users`, `agents`, `policies` (версии), `decisions`, `approvals`, `audit_events` (append-only триггер), `llm_trace`, `refresh_tokens` и др. — 14 всего.

## 5. API и UI

- API: 37 роутов, OpenAPI (`/docs`), генерируемый перечень — [API.md](API.md) (`docs/generate_api_md.py`).
- UI: один кокпит без сборки (никакого npm): агенты, лента решений с «Почему?» и «Переиграть», approvals-inbox, чат-задача, правила (Dharma) + словами + симулятор, отчёты (health/trust/drift/CSV), WS-индикатор, i18n RU/EN.
- События WS: `agent.status`, `decision.proposed`, `action.scheduled`, `approval.requested` (fan-out, авторизация токеном).

## 6. Инфраструктура

- Деплой: `Dockerfile` (uvicorn `--host 0.0.0.0 --port 8080`) + `docker-compose.yml` (backend+PG; redis — опциональный профиль).
- Dev: systemd user-юнит `karta-dev.service` на :8090 (`systemctl --user restart karta-dev`).
- Health: честный (`/api/v1/health`) — статусы postgres/redis/rpc/gigachat/telegram, без выдуманных «ok».
- CI: tests+SAST+dep-audit+secrets+contracts+slither+aderyn — см. [SECURITY.md](SECURITY.md).
