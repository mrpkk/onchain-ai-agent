# THREAT_MODEL.md — KARTA (STRIDE) · S0-04

> Создан 18.09.2026 по SPEC §8.7. Каждая угроза → контрмера → тест (когда реализовано).
> Статус: v0.1 (аудит 18.09, сверка с кодом **28.10.2026**). OWASP-чеклист обязателен при ревью.
> **Сверка 28.10:** часть ссылок на тесты не совпадала с репозиторием — исправлено ниже; там, где
> контрмера есть в коде, но теста нет, стоит `НЕТ ТЕСТА` (честно, а не «реализовано»).

## 1. Активы

| Актив | Ценность | Где живёт сейчас |
|---|---|---|
| Приватные ключи кошельков | Критическая (потеря = потеря средств) | `config.private_key` → WalletManager; KeyVault (задел) |
| Средства на кошельке | Критическая | Блокчейн |
| JWT/пароли пользователей | Высокая | in-memory (as-is) |
| Аудит-лог решений | Высокая (доказуемость) | in-memory (as-is) |
| Политики/лимиты | Высокая (границы автономии) | конфиг |
| Данные поставщиков (цены/газ) | Средняя | live-запросы |

## 2. Акторы и границы доверия

- **Владелец** (пользователь) — доверенный.
- **LLM** — недоверенный (может галлюцинировать/быть инжектированным).
- **Внешние данные** (token/contract metadata, новости, tool descriptions, RPC-ответы) — untrusted.
- **RPC-провайдеры** — частично доверенные (могут врать/задерживать).
- **Контрагенты ончейн** (контракты, пулы) — враждебные по умолчанию.

## 3. Угрозы → контрмеры → тесты

| # | Угроза (STRIDE) | Сценарий | Контрмера | Тест (слайс) |
|---|---|---|---|---|
| T1 | Prompt Injection (Tampering) | Метадата токена/строки контракта/новости содержат инструкции → LLM меняет действие | Внешние данные = DATA, изолированы от system-prompt; DATA ≠ INSTRUCTION; LLM выдаёт только скоры | **`test_attacks.py`** (инъекция меняет получателя → BLOCK/E03); на уровне API — **НЕТ ТЕСТА** |
| T2 | Adversarial-цены (Tampering) | Манипуляция ценой на одном источнике → агент «покупает дорого» | Multi-source оракул: медиана ≥2 источников, отклонение >2% → degraded; джиттер времени/размера | **НЕТ ТЕСТА** (есть `test_gas_oracle.py` — про газ, не про цену) |
| T3 | MEV / сэндвич (Info Disclosure + Tampering) | Фронтран агента на swap | Private RPC (Flashbots-класс), jitter, тир-лист веню | fork-тесты (P5/S5-05) |
| T4 | Компрометация ключа (Elevation) | Утечка ключа из логов/конфига/памяти | KeyVault + dual-key + session keys (TTL, revoke) + redaction + guard-тест `test_no_direct_key_access.py` | S1-04, S5-06 |
| T5 | Replay / nonce-race (Tampering) | Повторная подпись/гонка nonce | per-chain nonce-lock + reconcile с chain; idempotency-key для write | S5-04, MCP-тесты |
| T6 | Goal Hijacking (Tampering) | Инъекция меняет цель агента | NL-цель → compiled policy + превью владельцу; смена цели = событие Sakshi | **НЕТ ТЕСТА** (политика и Sakshi есть, теста на подмену цели нет) |
| T7 | Memory Poisoning (Tampering) | Отравление памяти агента ложными «фактами» | Память без секретов; preference-memory версионирована; факты только из provider-envelope | S2-06-тесты |
| T8 | Policy Bypass (Elevation) | Путь исполнения в обход Dharma | Все пути исполнения через `evaluate()`; `DHARMA_ENFORCE=on` в prod | **`test_dharma.py`**, **`test_policy_api.py`**, **`test_envelope.py`** (100 параллельных → ровно 50 разрешено) |
| T9 | Infinite Approve Drain (Elevation) | Дренаж через `approve(2^256-1)` | Запрет в коде/UI (raise `INFINITE_APPROVE_BLOCKED`), точные суммы + auto-revoke, Approval Guardian | `test_approve_security.py` (S1-05) |
| T10 | Fake Health / фантомные зависимости (Spoofing) | Система «здорова» при мёртвом Redis/PG | Реальные проверки в `/health`/`/health/deep`; `redis_connected` только из PING | `test_health_honesty.py` (S1-09) |
| T11 | Утечка через аудит/логи (Info Disclosure) | Ключи/секреты в логах/LLM-трейсах | Redaction, секреты только KeyVault, CI secret-scan + entropy | CI-гейт (S1-01) |
| T12 | Слабая аутентификация (Spoofing) | Брутфорс/кража пароля, угон JWT | Argon2id, JWT 15м/7д + rotation + reuse-detection, rate-limit login 5/мин | S1-02, S1-03 |

## 3a. Публичный контур KARTA (демо + MCP) — добавлено 28.10.2026

| # | Угроза | Сценарий | Контрмера | Тест |
|---|---|---|---|---|
| T13 | Подмена получателя | инъекция в данные просит заплатить новому вендору | allowlist в конверте | `test_attacks.py::prompt_injection_payee` → BLOCK/E03 |
| T14 | Отравленный инструмент завышает сумму | инструмент возвращает ×1000 цены | `per_call_max` проверяется вне модели | `test_attacks.py::tool_poisoning_amount` → BLOCK/E04 |
| T15 | Цикл на границе бюджета | 41 000 корректных платежей | бюджет принадлежит задаче | `test_attacks.py::runaway_loop`; `test_x402_guard.py` 1 000 → 500 |
| T16 | Гонка при параллельных списаниях | 100 одновременных запросов | `BEGIN IMMEDIATE`, проверка и списание в одной транзакции | `test_ledger_concurrency.py` |
| T17 | Остановка не срабатывает | kill «проходит», а списание идёт | `ON CONFLICT`, проверка `kills` в транзакции | `test_ledger_kill.py` (регрессия тихого отказа 27.10) |
| T18 | Подделка квитанции/пакета | правка JSON после выдачи | Ed25519-подпись, sha256, офлайн-проверка | `test_killswitch_evidence.py`, `test_envelope.py` |

## 4. Принципы

- **Zero Trust Input:** LLM, tool descriptions, RPC-ответы, память — недоверенные.
- **Least Privilege:** session keys со scope+TTL; MCP write-tools за permission-gate.
- **Defense in Depth:** аккаунт-политики (ERC-4337) дублируются Dharma-движком.
- **Fail-Safe:** ошибка любого слоя → hold + ask_human (critical), без слепых retry.
- **Auditability:** ни один слой не контролирует pipeline единолично.

## 5. Открытые решения

- Dual-key/session keys — целевая схема (S5-06): owner-ключ offline, executor-ключ со scope.
- KYT/санкционный скрининг — опция Enterprise (WATCH, правовой анализ).
- TEE/HSM адаптеры — интерфейсы KeyVault v2 (S1-04), реализация — FUTURE LAB (F6).
