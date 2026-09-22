# KARTA — Security Posture (as-built)

> Источник истины — код. Документ фиксирует, что реализовано и чем проверяется.
> Модель угроз: [THREAT_MODEL.md](THREAT_MODEL.md) (STRIDE, T1–T12). Аудит: [AUDIT_REPORT.md](AUDIT_REPORT.md).

## 1. Секреты и ключи

| Слой | Реализация |
|---|---|
| Хранение | секреты только в master-`~/.env` (chmod 600); `backend/.env` из контура выведен |
| Аккаунты | Argon2id (`pwdlib`), миграция legacy-хешей при логине |
| Кошельки | `security/keyvault.py` — lazy-init, ключ не покидает vault-слой; в лог не пишется |
| CI | secret-scan (hex-ключи) + **gitleaks**; `.env*` в `.gitignore` |

## 2. Аутентификация и доступ

- **JWT HS256**: access + refresh; refresh с **ротацией**, **reuse-detection** (повтор ротированного токена отзывает family), `revoke-all`; rate-limit на логин/refresh.
- **Ownership**: все агентские ресурсы проверяют владельца → чужие id = 404 (не 403).
- **Scoped approve**: одобрение с `max`/безлимитом запрещено на уровне API; отзыв `revoke_approve`; Approval Guardian классифицирует риск (блок-лист, `2^256-1`, порог review).
- **Единый путь approvals**: web-кокпит и Telegram приходят в один `runtime/approvals.resolve_approval`; Telegram **не обходит** Dharma-гейты.
- **Kill-switch**: soft/hard, терминальный; проверяется во всех путях исполнения.
- **Dead-man switch**: отсутствие heartbeat → hard kill без авто-возобновления (audit `deadman_triggered`).

## 3. Политики (Dharma Engine)

- Версионируемый DSL (YAML) → `CompiledPolicy` (pydantic, fail-closed).
- Любое изменение — **новая версия** через явный `PUT` (и «правила словами» тоже: NL→патч→превью→PUT).
- Тир 0–1: `simulation_mode` (исполнение запрещено); тир 2–3: исполнение за гейтами.
- **Policy Simulator** — impact-превью кандидата на истории решений, без применения.

## 4. Аудит (Sakshi Log)

- Append-only: HMAC-цепочка (keyed hash), запись каждого решения/старта/гейта.
- PG-триггер запрещает UPDATE/DELETE (проверено тестом).
- Экспорт CSV включает хвост hash-цепочки — аудируемость вне системы.

## 5. LLM-слой

- Цепочка провайдеров с авто-fallback и breaker; structured output с repair-циклом.
- `llm_trace`: request_id, agent_id, provider, cost, prompt_version (версионирование промптов).
- GigaChat: TLS-проверка по **Trusted Root CA НУЦ Минцифры** (`backend/src/security/certs/`, env `GIGACHAT_CA_BUNDLE`); `verify=False` исключён.

## 6. Контракты

- 56 hardhat-тестов (agent-контракты, timelock, escrow, mock), mock-режим без реальных сетей.
- **Slither** — fail on high; **Aderyn** — soft-check; в CI на каждый push.

## 7. CI-гейты

| Гейт | Команда | Режим |
|---|---|---|
| Backend tests | `pytest backend/tests -q` (218) | fail |
| SAST | `bandit -r backend/src --severity-level medium` | fail (0 находок) |
| Dep-audit | `pip-audit -r backend/requirements.txt` | fail (0 уязвимостей) |
| Секреты | `gitleaks` + hex-scan | fail |
| Контракты | `npx hardhat test` (56) | fail |
| Slither | высокие severity | fail |
| Aderyn | отчёт | soft |

## 8. Честные ограничения (не выдавать за готовое)

- KeyVault — программный (файловый AES-контур уровня S1); **HSM/TEE/KMS — Phase 6+ (F6)**.
- Multi-tenant изоляция ключей — одна инсталляция на владельца (SaaS-мультиарендность — P6+).
- EVM-контракты не аудированы внешними аудиторами (внутренние тесты + статанализ).
- Полное перечисление approvals кошелька невозможно без индексатора — сканируются известные пары (реализовано и подписано честно).
