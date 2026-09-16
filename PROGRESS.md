# KARTA (onchain-ai-agent) — Progress v2

> Ветка: `feature/v2-modernization` · Эталон-промпт: `projectBooks/OnChain_AI_Agent_MODERNIZATION.md`
> Правило: слайс = код + тест + docs + зелёный прогон + коммит. Без этого чекбокс не закрывается.

## Current Phase
PHASE 1 — Безопасность (P0-фиксы)

## Completed
- [x] PHASE 0 — Аудит: `docs/AUDIT_REPORT.md` (evidence-based), 6/6 тестов зафиксированы, P0/P1/P2 выявлены — `dbf5de4`
- [x] Ребрендинг: KARTA + karma/dharma/sakshi одобрены, лого-концепты в `branding/` — `dbf5de4`

## In Progress
- [ ] P0-1: KeyVault-миграция — убрать `config.private_key` из `core.py:98-99`
- [ ] P0-2: запрет max-approve (`execution.py:261`) — только точные суммы
- [ ] P0-3: Argon2id/bcrypt вместо sha256+salt (`main.py:52-59`) + миграция хешей
- [ ] P0-4: честный /health — реальные проверки PG/Redis/RPC/LLM
- [ ] P0-5: тесты Escrow + RicardianAgreement; Slither в CI

## Backlog
- [ ] PHASE 2 — PG+Alembic реально, WS-события, трейсинг решений
- [ ] PHASE 3 — Policy Engine (Dharma), simulation-сервис (fork), kill-switch drill
- [ ] PHASE 4 — Кокпит UX, чат-first, Telegram approve, онбординг ≤5 мин
- [ ] PHASE 5 — swap/bridge, ERC-4337 session keys, private RPC
- [ ] PHASE 6 — ERC-8004 репутация, Escrow-аренда, MCP-сервер

## STOP GATES (ждут решения владельца)
- [ ] Execution-граница (v2 = READ+SIMULATE+PROPOSE?)
- [ ] Хранение (PG локально через docker-compose?)
- [ ] LLM-цепочка (DeepSeek-ключ в ~/.env?)
- [ ] Перенос backend/.env → ~/.env, chmod 600
- [ ] Футуристики: F3→F2→F1→F8→F5
- [ ] EU-VPS только на этапе публичного запуска

## Next Action
Ответы владельца по STOP GATES → старт P0-1 (KeyVault-миграция).
