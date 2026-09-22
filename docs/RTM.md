# RTM — onchain-ai-agent
> RTM создан 21.08.2026. Статусы: ✅/🟡/❌.

---

## ⚡ AS-BUILT (обновлено 2026-09-18, модернизация KARTA v2)

> Таблицы ниже — **исторический снимок 21.08.2026** (до модернизации). Актуальный статус — здесь.
> Источник истины по слайсам — `PROGRESS.md` (P0–P4 закрыты; 221 backend-тест + 56 контрактных; live-смоук 13/13).

| RTM | As-built 2026-09-18 | Доказательство |
|---|---|---|
| FR-1 Perception | ✅ баланс/газ/мемпул: реальный сканер мемпула, честный `rpc_unavailable` вместо выдумок | S2-07, `tests/test_mempool.py` |
| FR-2 Reasoning | ✅ LLM-цепочка **GigaChat→DeepSeek→Qwen→РФ-агрегаторы→Ollama** (Mistral исключён — блок РФ), structured output + repair + breaker, prompt-версии | S2-05, `tests/test_llm_router.py` |
| FR-3 Planning | ✅ + chat-first: NL→intent с Dharma-превью и подтверждением | S4-03, `tests/test_intent.py` |
| FR-4 Execution | ✅ полный контур policy→simulation→timelock→dispatch (тиры 2–3); реальное on-chain — **P5 (STOP-GATE)** | S3-02/03, P4 |
| FR-5 Multi-chain | 🟡 config-адаптер сетей — **P5 (S5-07)** | — |
| FR-6 WalletManager | ✅ KeyVault lazy-init, ключ не покидает vault-слой; guard-тест «LLM не получает ключ» | S1-04, `tests/test_agent_keyvault.py` |
| FR-7 Spending limits | ✅ **Dharma DSL**: версии, per-tx/daily, allow/deny/require_approval, fail-closed | S1-06, `tests/test_dharma.py` |
| FR-8 Simulation mode | ✅ дефолт тиров 0–1; авто-политика тира при создании агента | S4-04, `runtime/tiers.py` |
| FR-9 Контракты | ✅ компилируются (4 бага починены), 56 тестов, Slither fail-on-high + Aderyn в CI | S1-07 |
| FR-10 JWT | ✅ access+refresh, ротация, reuse-detection, revoke-all, rate-limit; **PyJWT** | S1-03, S4-15 |
| FR-11 Safety | ✅ kill-switch (soft/hard), dead-man switch + реконсиляция при старте, Sakshi HMAC-аудит (append-only PG-триггер) | S1-08, S3-04, S4-17 |
| NFR-1 KeyVault | ✅ (см. FR-6); миграция env-ключей в vault — при деплое | S1-04 |
| NFR-2 Аудит контрактов | ✅ статанализ (Slither+Aderyn) в CI; **внешний аудит — нет** (честно, P6+ при необходимости) | CI |
| NFR-3 Security-тесты | ✅ 221 backend + 56 контрактных + coverage-гейт 80% + live-смоук `scripts/e2e_live.py` | S4-15/17 |
| NFR-4 CI/CD | ✅ tests+coverage+**bandit+pip-audit**+gitleaks+contracts+Slither | `.github/workflows/ci.yml` |
| NFR-5 Лимиты/газ | 🟡 лимиты ✅ (Dharma); газ-оракул/EIP-1559 — **P5 (S5-04)** | — |

---

## 1. Продуктовая цель
| Поле | Значение |
|---|---|
| Vision | Автономный AI-агент с EVM-кошельком: восприятие → CoT-рассуждение → план → исполнение транзакций, с жёсткими лимитами безопасности |
| Целевой пользователь | Web3-разработчики/фонды; white-label для агентных платформ |
| Монетизация | Лицензия/интеграция; витрина навыка «AI×Blockchain» в портфолио |

## 2. Функциональные требования
| ID | Требование | Приоритет | Модуль | As-is | To-be |
|---|---|---|---|---|---|
| FR-1 | Perception: мониторинг блокчейна, оракулы цен | Must | backend/perception | 🟡 | ✅ + тесты источников |
| FR-2 | Reasoning CoT (Mistral) | Must | backend/reasoning | ✅ | ✅ |
| FR-3 | Planning: построение плана действий | Must | backend/planning | ✅ | ✅ + dry-run плана |
| FR-4 | Execution: перевод ETH, вызовы контрактов, approve | Must | backend/execution | ✅ | ✅ |
| FR-5 | Multi-chain: ETH/BSC/Polygon/Sepolia | Should | backend/chains | ✅ | ✅ |
| FR-6 | WalletManager create/import/list | Must | backend/wallet | ✅ | ✅ + шифрование ключей at rest ⚠️ проверить |
| FR-7 | Spending limits: дневной и per-tx | Must | backend/limits | ✅ | ✅ тесты обхода |
| FR-8 | Simulation mode (без реальных средств) | Must | backend/ | ✅ | ✅ дефолт включён |
| FR-9 | Контракты: AgentRegistry / Escrow / RicardianAgreement | Should | smart-contracts/ | ✅ код | ✅ аудит + тесты Foundry |
| FR-10 | JWT аутентификация API | Must | backend/auth | ✅ | ✅ + refresh/ротация |
| FR-11 | Blacklist/whitelist адресов, kill switch, audit log | Must | backend/safety | ✅ | ✅ e2e-тест kill switch |

## 3. Нефункциональные требования
| ID | Требование | As-is | To-be |
|---|---|---|---|
| NFR-1 | Ключи: KeyVault (Fernet+PBKDF2, chmod 600), инкапсуляция в WalletManager, security-gate на старте | ✅ (21.08, 6 тестов) | миграция существующих env-ключей в vault |
| NFR-2 | Аудит смарт-контрактов | ❌ | Минимум: статический анализ (Slither) + тесты покрытия |
| NFR-4→3 | Security-тесты: 6 passed (21.08); CI workflow добавлен | 🟡 | + сценарии отказов RPC |
| NFR-4 | CI/CD | ❌ | Actions: lint+test+slither |
| NFR-5 | Rate limits и газовые политики | 🟡 | Политики газа, слippage-лимиты |

## 4. Разрывы до коммерческого продукта
1. **Аудит хранения приватных ключей** — критический блокер любого продакшна.
2. Контракты без аудита и покрытия тестами.
3. Нет CI, нет нагрузочных/отказных тестов RPC.
4. Юридический статус «автономного агента, подписывающего сделки» — дисклеймеры.

## 5. План переработки
| Этап | Содержание | Статус |
|---|---|---|
| 0. Спека | Угрозовая модель (threat model) агента | ❌ |
| 1. Архитектура | Модуль KeyVault, policy-engine лимитов | ❌ |
| 2. Реализация | NFR-1, покрытие контрактов тестами | ❌ |
| 3. Тесты | Fork-тестирование против testnet, kill-switch drill | ❌ |
| 4. Релиз | Slither+покрытие в CI, security.md | ❌ |
