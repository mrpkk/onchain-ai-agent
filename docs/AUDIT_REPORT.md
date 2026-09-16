# AUDIT REPORT — onchain-ai-agent (KARTA v2, Phase 0)

> Дата: 2026-09-16 · Ветка: `feature/v2-modernization` · Метод: evidence-based (`file:line`)
> Статус: аудит завершён, код НЕ менялся (кроме branding/)

## 1. Исходное состояние

| Параметр | Значение |
|---|---|
| Последний коммит (main) | `7f129f1 feat: GigaChat первичный провайдер LLM` |
| Ветка аудита | `feature/v2-modernization` (создана 16.09) |
| Backend-тесты | **6/6 passed** (pytest 9.0.2, python3.14, system python; `.venv` без pytest) |
| Контракт-тесты | только `AgentRegistry.test.js` (27 describe/it) — Escrow/RicardianAgreement **без тестов** |
| Секрет-скан (rg по repo, gitignore-aware) | 0 находок в git |
| Запуск API | `uvicorn src.api.main:app --port 8000` (из backend/), systemd-юнитов нет |

## 2. Actual vs Claimed

| Элемент | Заявлено (README/книга) | Факт | Статус | Evidence |
|---|---|---|---|---|
| PostgreSQL/SQLAlchemy/Alembic | подключены | in-memory dict'ы | **MOCK/PHANTOM** | `api/main.py:67-69` (`_users_db`, `_agents_db`) |
| Redis | подключён, healthcheck | `redis_connected=True` хардкод | **FAKE** | `api/main.py:304` |
| Эндпоинты | 16 | 13 роут-декораторов | **DRIFT** | `grep @app.` = 13 |
| KeyVault миграция | завершена | `config.private_key` читается напрямую | **P0** | `agent/core.py:98-99` |
| Approve | безопасный | `2**256 - 1` по умолчанию | **P0** | `agent/execution.py:261` |
| Пароли | JWT+Passlib (README) | самописный `sha256+salt` | **P0** | `api/main.py:52-59` |
| MempoolMonitor | мониторинг мемпула | пустая заглушка | **NOT_IMPLEMENTED** | `agent/perception.py` |
| swap/bridge/deploy | в списке действий LLM | не исполняются (`_execute_decision` без веток) | **NOT_IMPLEMENTED** | `agent/core.py:289-323` |
| JWT refresh/ротация | — | нет | **MISSING** | `api/main.py:103-109` |
| Rate limits | — | нет | **MISSING** | — |
| Escrow/RicardianAgreement | готовы | без тестов, не аудированы | **P0** | `smart-contracts/test/` |
| `backend/.env` | защищён | живые `MISTRAL_API_KEY`+`GITHUB_TOKEN`, права **664** | **P1** | `ls -la backend/.env` |
| Сетей заявлено | 6 (README) | 4 в коде (eth/bsc/polygon/sepolia) | **DRIFT** | `agent/perception.py` |

## 3. Findings (severity)

### P0 — блокеры продакшна
1. `core.py:98` — прямой доступ к приватному ключу из конфига (миграция на KeyVault не завершена).
2. `execution.py:261` — max-approve `2^256-1` по умолчанию.
3. `main.py:52-59` — самописный sha256+salt для паролей.
4. `main.py:304` — фейковый Redis health.
5. Контракты Escrow/RicardianAgreement без тестов и аудита.

### P1 — важные
6. `backend/.env` с живыми ключами, chmod 664 (не 600), находится в рабочей папке (не `~/.env`).
7. README↔код: 16 vs 13 эндпоинтов, 6 vs 4 сети, «Passlib» vs самописный хэш.
8. In-memory БД — все данные теряются при рестарте; аудит-лог в памяти.
9. Лимиты из settings не применяются во всех путях исполнения.
10. JWT без refresh/revocation/rate-limit.

### P2 — техдолг
11. MempoolMonitor — заглушка; swap/bridge/deploy объявлены, не реализованы.
12. Нет threat model, policy engine, fork-тестов, kill-switch drill, Slither в CI.
13. `.venv` (py3.14) без pytest; CI заявлен на py3.12 — локальный прогон только через system python.

## 4. Вердикт

Ядро (конвейер perception→reasoning→planning→execution + KeyVault-каркас + RiskAssessor + kill switch) рабочее: 6/6 security-тестов зелёные. Но продукт продавать нельзя: P0-пункты 1–5 нарушают базовые правила хранения ключей и токен-безопасности. Первые 4 часа Phase 1 — фикс P0.

## 5. STOP-GATE вопросы владельцу (не двигаемся без ответов)

1. **Execution-граница:** подтвердить «v2 = READ+SIMULATE+PROPOSE, реальное исполнение — за флагом»?
2. **Хранение:** PostgreSQL реально разворачиваем локально (docker-compose уже есть) — ок?
3. **LLM:** цепочка GigaChat→DeepSeek→Qwen→агрегаторы→Ollama — ок? DeepSeek-ключ нужен (есть ли в ~/.env)?
4. **Права на backend/.env:** перенести ключи в ~/.env и выставить 600?
5. **Футуристики:** комбо F3→F2→F1→F8→F5 подтверждаем?
6. **Деплой:** локальный + docker-compose достаточно; EU-VPS — только на этапе публичного запуска?
