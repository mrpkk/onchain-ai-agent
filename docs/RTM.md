# RTM — onchain-ai-agent
> RTM создан 21.08.2026. Статусы: ✅/🟡/❌.

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
| NFR-1 | Безопасность ключей: где хранится приватник | ⚠️ аудит обязателен | KMS/шифрование, никогда в БД plaintext |
| NFR-2 | Аудит смарт-контрактов | ❌ | Минимум: статический анализ (Slither) + тесты покрытия |
| NFR-3 | Тесты backend | 🟡 | pytest + сценарии отказов RPC |
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
