# Changelog

Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/) · версии — по тегам репозитория.

## [v2.0-beta] — 2026-09-24

Модернизация **KARTA**: исполнение 2.0 (P5) и агент-экономика (P6).

### Добавлено
- **P5 «Исполнение 2.0» (7/7):**
  - EIP-1559 + газ-оракул (base+priority → maxFeePerGas с буфером, TTL-кэш, кап политики = HOLD).
  - Private RPC (Flashbots Protect / MEV Blocker — проверены из РФ) + jitter перед отправкой; mainnet-only с честным fallback.
  - Multi-chain реестр: 6 сетей (Ethereum, Sepolia, **Base**, Base Sepolia, BSC, Polygon) с RPC-fallback, explorer, finality-эвристикой и health-кэшем; API `/api/v1/chains`.
  - Swap: MockDEX (Uniswap-V2-совместимый, x·y=k, 0.30%), slippage-guard (Dharma + сервис), price-impact; API `/api/v1/swap/*`.
  - Bridge: реальные котировки/статус LI.FI (AcrossV4 и др.); исполнение gated (`BRIDGE_EXECUTION_ENABLED`, STOP-GATE реальных средств).
  - ERC-4337 (локальный контур): KartaEntryPoint, KartaSmartAccount (**session keys: TTL/лимит/цель**, guardians-recovery 2-of-N), MockPaymaster; API `/api/v1/erc4337/*`.
  - Деплой на Sepolia: AgentRegistry, Escrow, RicardianAgreement, MockERC20, MockDEX, xUSDC (EIP-3009), KartaEntryPoint/SmartAccount/MockPaymaster.
- **P6 «Агент-экономика» (5/5):**
  - MCP-сервер (streamable HTTP, stateless): 8 read-tools, API-ключи `karta_`, OWASP-хардening, контракты+parity-тесты; `docs/MCP.md`.
  - Ricardian 2-of-3: API + панель кокпита, полный anvil-цикл, live Sepolia.
  - ERC-8004: паспорт агента (публичный metadataURI) + бейджи (on-chain/verified/reputation/health/trust/tier).
  - Escrow-аренда агентов: approve+create, release/refund/dispute/resolve; API + панель.
  - x402-демо (тестнет): EIP-3009-токен, 402-челлендж, локальная верификация, сеттлмент, replay-защита; `docs/X402.md`.
- **UX:** панели Swap / Bridge / ERC-4337 в кокпите, i18n RU/EN.
- **Документы:** `docs/API.md` (авто-генерация, 75 роутов), `docs/MCP.md`, `docs/MCP_TOOL_CONTRACTS.md`, `docs/X402.md`, `docs/RTM.md` (as-built), `docs/DEPLOYMENT.md`.
- **CI:** bandit (medium+), pip-audit, coverage-гейт 80%, gitleaks, Slither/Aderyn, `node --check` для статики.
- **Тесты:** 328 backend + 76 контрактных; live-регресс `scripts/e2e_live.py` (агент + модули P5/P6).

### Исправлено
- Timelock для plan-step пути (шаги плана проходят undo-window наравне с решениями).
- `resolveName=0`-неоднозначность в реестре агентов (живая находка), мёртвые RPC из РФ, nonce-гонки RPC, блокировка event loop при отправке транзакций.

## [v2.0-alpha] — 2026-09-22

Первая фаза модернизации: аудит, безопасность, фундамент, политики, кокпит.

### Добавлено
- **P0:** evidence-based аудит (AUDIT_REPORT, ARCHITECTURE_CURRENT, THREAT_MODEL STRIDE T1–T12), RTM.
- **P1 «Безопасность» (9/9):** Argon2id, JWT с ротацией/reuse-detection, KeyVault, scoped approve, Dharma Engine (DSL-политики), контракты+Slither/Aderyn, kill-drill, честный `/health`, секреты выведены из репозитория.
- **P2 «Фундамент» (8/8):** PostgreSQL + Alembic (15 таблиц), Sakshi Log (HMAC-аудит, append-only), WebSocket live-события, LLMProvider-цепочка (GigaChat→…), трейсинг, реальный мемпул.
- **P3 «Политики/симуляция» (5/5):** Simulation-гейт, Timelock/undo, dead-man switch, Guardian, API⟷Runtime-интеграция.
- **P4 «Кокпит» (10/10):** дизайн-токены, кокпит (лента решений, approvals, чат-задачи, отчёты, экспорт CSV), тиры 0–3 + мастер, Intent→Guarantee, Policy Simulator, Trust Ladder, Drift, Replay, i18n RU/EN, лого K.
- **Тесты:** ~221 backend + 56 контрактных.

[v2.0-beta]: https://github.com/mrpkk/onchain-ai-agent/releases/tag/v2.0-beta
[v2.0-alpha]: https://github.com/mrpkk/onchain-ai-agent/releases/tag/v2.0-alpha
