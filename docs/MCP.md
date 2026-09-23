# KARTA MCP — подключение

> KARTA отдаёт **read-only MCP-сервер** (streamable HTTP, stateless) — локально-первый этап S6-04.
> Write-tools (execute/pause/kill) — gated, в v1 не зарегистрированы (см. `MCP_TOOL_CONTRACTS.md`).

## 1. Выпуск API-ключа

```bash
# JWT: логин
TOKEN=$(curl -s -X POST http://127.0.0.1:8090/api/v1/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"<вы>","password":"<пароль>"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# Ключ (scope mcp:read); плейн-ключ показывается ОДИН раз
curl -s -X POST http://127.0.0.1:8090/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"cursor","scopes":["mcp:read"]}'
```

## 2. Эндпоинт

```
POST http://127.0.0.1:8090/mcp
Authorization: Bearer karta_…
Content-Type: application/json
Accept: application/json, text/event-stream
```

Проверка вручную:

```bash
curl -s http://127.0.0.1:8090/mcp \
  -H 'Authorization: Bearer karta_…' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## 3. Подключение клиентов

### Claude Desktop / Claude Code (локально)

`claude_desktop_config.json` (или `.mcp.json`):

```json
{
  "mcpServers": {
    "karta": {
      "type": "http",
      "url": "http://127.0.0.1:8090/mcp",
      "headers": { "Authorization": "Bearer karta_…" }
    }
  }
}
```

### Cursor

`.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "karta": {
      "url": "http://127.0.0.1:8090/mcp",
      "headers": { "Authorization": "Bearer karta_…" }
    }
  }
}
```

### OpenCode / другие MCP-клиенты

Любой клиент с поддержкой **streamable HTTP MCP**: URL `http://127.0.0.1:8090/mcp`, заголовок `Authorization`.

## 4. Безопасность (OWASP MCP)

- **Tool-poisoning:** определения tools pinned в `backend/src/mcp/contracts.py` + parity-тест.
- **Prompt-injection:** tools не ходят по адресам/URL из аргументов — только БД/RPC по своим агентам.
- **Excessive agency:** в v1 только read; write-tools не зарегистрированы (тест `test_write_tools_not_registered`).
- **Confused deputy:** каждый вызов аутентифицируется ключом; данные строго в скоупе владельца.
- **Credential leakage:** секреты не логируются, ошибки структурированы (`{"error": {"code","message","hint"}}`).
- **DNS-rebinding:** Host-allowlist (`KARTA_MCP_ALLOWED_HOSTS`, по умолчанию localhost).

## 5. Деплой-доступ (когда понадобится)

Публичный доступ — этап 2: выставить сервис за TLS-прокси, добавить домен в `KARTA_MCP_ALLOWED_HOSTS`,
ключи с scope `mcp:read` — только для доверенных партнёров. Решение владельца (бюджет VPS — открыт).
