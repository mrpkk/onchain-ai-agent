# KARTA API

> AUTO-GENERATED: `docs/generate_api_md.py` (источник — OpenAPI приложения).
> Роутов: **75** · тегов: **1**. SwaggerUI: `/docs`.

## Безопасность

- Почти все приватные роуты требуют `Authorization: Bearer <access_token>` (JWT, HS256; refresh с ротацией и reuse-detection).
- Все агентские ресурсы проверяют **ownership** (агент принадлежит текущему пользователю) → чужие id дают 404.
- Approvals приходят из двух транспортов (web/TG) в **единый** `resolve_approval` → полный контур policy→simulation→timelock.
- Аудит (Sakshi Log) — HMAC-цепочка; экспорт CSV включает хвост hash-цепочки.

## /

| Метод | Путь | Назначение | Ответы |
|---|---|---|---|
| `GET` | `/` | Root Page | 200 |
| `POST` | `/api/v1/agents` | Create Agent | 201, 422 |
| `GET` | `/api/v1/agents` | List Agents | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}` | Get Agent | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/audit` | List Audit Events | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/decisions` | List Decisions | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/drift` | Agent Drift | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/export.csv` | Agent Export Csv | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/goal` | Set Goal | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/heartbeat` | Agent Heartbeat | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/intent` | Parse Agent Intent | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/intent/confirm` | Confirm Agent Intent | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/kill-switch` | Kill Switch | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/pending` | List Pending Actions | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/pending/{pending_id}/cancel` | Cancel Pending Action | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/policy` | Get Agent Policy | 200, 422 |
| `PUT` | `/api/v1/agents/{agent_id}/policy` | Put Agent Policy | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/policy/from-text` | Policy From Text | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/policy/simulate` | Simulate Agent Policy | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/registry` | Agent Registry Info | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/registry` | Agent Registry Register | 201, 422 |
| `POST` | `/api/v1/agents/{agent_id}/registry/sync-reputation` | Agent Registry Sync Reputation | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/registry/verify` | Agent Registry Verify | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/reports/summary` | Agent Report Summary | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/start` | Start Agent | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/stop` | Stop Agent | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/tier` | Set Agent Tier | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/transactions` | List Transactions | 200, 422 |
| `GET` | `/api/v1/api-keys` | List Api Keys | 200 |
| `POST` | `/api/v1/api-keys` | Create Api Key | 201, 422 |
| `DELETE` | `/api/v1/api-keys/{key_id}` | Revoke Api Key | 200, 422 |
| `GET` | `/api/v1/approvals` | List Approvals | 200, 422 |
| `POST` | `/api/v1/approvals/{approval_id}/approve` | Approve Approval | 200, 422 |
| `POST` | `/api/v1/approvals/{approval_id}/reject` | Reject Approval | 200, 422 |
| `POST` | `/api/v1/auth/logout` | Revoke All Tokens | 200 |
| `POST` | `/api/v1/auth/refresh` | Refresh Tokens | 200, 422 |
| `POST` | `/api/v1/auth/register` | Register | 201, 422 |
| `POST` | `/api/v1/auth/revoke-all` | Revoke All Tokens | 200 |
| `POST` | `/api/v1/auth/token` | Login | 200, 422 |
| `POST` | `/api/v1/bridge/execute` | Bridge Execute | 200, 422 |
| `GET` | `/api/v1/bridge/info` | Bridge Info | 200 |
| `GET` | `/api/v1/bridge/quote` | Bridge Quote | 200, 422 |
| `GET` | `/api/v1/bridge/status` | Bridge Status | 200, 422 |
| `GET` | `/api/v1/chains` | List Chains | 200 |
| `GET` | `/api/v1/decisions/{decision_id}` | Get Decision Replay | 200, 422 |
| `POST` | `/api/v1/erc4337/guardians` | Aa Add Guardian | 201, 422 |
| `GET` | `/api/v1/erc4337/info` | Aa Info | 200 |
| `POST` | `/api/v1/erc4337/session-keys` | Aa Add Session Key | 201, 422 |
| `DELETE` | `/api/v1/erc4337/session-keys/{key_address}` | Aa Revoke Session Key | 200, 422 |
| `POST` | `/api/v1/erc4337/userop` | Aa Execute Userop | 200, 422 |
| `GET` | `/api/v1/escrow` | Escrow List | 200, 422 |
| `POST` | `/api/v1/escrow` | Escrow Create | 201, 422 |
| `GET` | `/api/v1/escrow/wallet` | Escrow Wallet | 200 |
| `GET` | `/api/v1/escrow/{escrow_id}` | Escrow Detail | 200, 422 |
| `POST` | `/api/v1/escrow/{escrow_id}/dispute` | Escrow Dispute | 200, 422 |
| `POST` | `/api/v1/escrow/{escrow_id}/refund` | Escrow Refund | 200, 422 |
| `POST` | `/api/v1/escrow/{escrow_id}/release` | Escrow Release | 200, 422 |
| `POST` | `/api/v1/escrow/{escrow_id}/resolve` | Escrow Resolve | 200, 422 |
| `GET` | `/api/v1/health` | Health | 200 |
| `POST` | `/api/v1/policies/validate` | Validate Policy | 200, 422 |
| `GET` | `/api/v1/registry/agents/{agent_id}/metadata` | Registry Public Metadata | 200, 422 |
| `GET` | `/api/v1/ricardian/agreements` | Ricardian List | 200, 422 |
| `POST` | `/api/v1/ricardian/agreements` | Ricardian Create | 201, 422 |
| `GET` | `/api/v1/ricardian/agreements/{agreement_id}` | Ricardian Detail | 200, 422 |
| `POST` | `/api/v1/ricardian/agreements/{agreement_id}/milestones/{index}/dispute` | Ricardian Dispute | 200, 422 |
| `POST` | `/api/v1/ricardian/agreements/{agreement_id}/milestones/{index}/execute` | Ricardian Execute | 200, 422 |
| `POST` | `/api/v1/ricardian/agreements/{agreement_id}/sign` | Ricardian Sign | 200, 422 |
| `GET` | `/api/v1/ricardian/wallet` | Ricardian Wallet | 200 |
| `GET` | `/api/v1/swap/aggregator` | Swap Aggregator | 200, 422 |
| `POST` | `/api/v1/swap/execute` | Swap Execute | 200, 422 |
| `GET` | `/api/v1/swap/info` | Swap Info | 200 |
| `GET` | `/api/v1/swap/quote` | Swap Quote | 200, 422 |
| `GET` | `/api/v1/x402/demo/premium` | X402 Demo Premium | 200 |
| `GET` | `/health` | Root Health | 200 |
| `GET` | `/health/deep` | Deep Health | 200 |

