# Installing KARTA

KARTA is a remote MCP server: no local process, no build step, no API key for the free tier.

## Option 1 — remote (recommended)

Add this to your MCP client configuration:

```json
{
  "mcpServers": {
    "karta": {
      "url": "https://karta.rta.lat/mcp",
      "transport": "streamable-http"
    }
  }
}
```

Verify it works:

```bash
curl -s -X POST https://karta.rta.lat/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
```

A JSON-RPC result means the server is reachable. Then call any tool:

- `open_envelope` — create a signed task budget (budget, allowed payees, no subscriptions, expiry)
- `check_spend` — ask whether a payment is allowed, get `ALLOW / HOLD / BLOCK` with a rule id
- `kill` — stop one envelope
- `receipt` / `verify_receipt` — issue and verify an Ed25519 receipt offline

## Option 2 — local (Docker)

```bash
docker run -d -p 8295:8295 ghcr.io/mrpkk/karta-demo:0.1.0
curl -s http://127.0.0.1:8295/health
```

Then point the client at `http://127.0.0.1:8295/mcp`.

## Option 3 — from source (ten minutes)

```bash
git clone https://github.com/mrpkk/onchain-ai-agent.git
cd onchain-ai-agent/backend
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m uvicorn src.demo.app:app --host 127.0.0.1 --port 8295
```

Full instructions: https://karta.rta.lat/pilot · API reference in plain text: https://karta.rta.lat/llms.txt

## What this server does not do

It does not move funds and does not hold keys. It decides whether a spend is inside a task
envelope and returns evidence. Mainnet payment execution is disabled by default.
