# KARTA API

> AUTO-GENERATED: `docs/generate_api_md.py` (источник — OpenAPI приложения).
> Роутов: **37** · тегов: **1**. SwaggerUI: `/docs`.

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
| `GET` | `/api/v1/agents/{agent_id}/reports/summary` | Agent Report Summary | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/start` | Start Agent | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/stop` | Stop Agent | 200, 422 |
| `POST` | `/api/v1/agents/{agent_id}/tier` | Set Agent Tier | 200, 422 |
| `GET` | `/api/v1/agents/{agent_id}/transactions` | List Transactions | 200, 422 |
| `GET` | `/api/v1/approvals` | List Approvals | 200, 422 |
| `POST` | `/api/v1/approvals/{approval_id}/approve` | Approve Approval | 200, 422 |
| `POST` | `/api/v1/approvals/{approval_id}/reject` | Reject Approval | 200, 422 |
| `POST` | `/api/v1/auth/logout` | Revoke All Tokens | 200 |
| `POST` | `/api/v1/auth/refresh` | Refresh Tokens | 200, 422 |
| `POST` | `/api/v1/auth/register` | Register | 201, 422 |
| `POST` | `/api/v1/auth/revoke-all` | Revoke All Tokens | 200 |
| `POST` | `/api/v1/auth/token` | Login | 200, 422 |
| `GET` | `/api/v1/decisions/{decision_id}` | Get Decision Replay | 200, 422 |
| `GET` | `/api/v1/health` | Health | 200 |
| `POST` | `/api/v1/policies/validate` | Validate Policy | 200, 422 |
| `GET` | `/health` | Root Health | 200 |
| `GET` | `/health/deep` | Deep Health | 200 |

