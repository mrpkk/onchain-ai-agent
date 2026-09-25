#!/usr/bin/env python3
"""KARTA live E2E-смоук (13 проверок) против запущенного сервера.

Проверяет живой контур: auth → agent(tier) → policy from-text (LLM) →
simulate → intent (LLM) → WS → start/stop → decisions → drift → replay →
summary(health/trust) → CSV export → approvals → Sakshi audit.

Запуск (dev-сервер karta-dev на :8090, пользователь должен существовать):
    python3 scripts/e2e_live.py
Переменные окружения (опционально):
    KARTA_E2E_BASE   (default http://127.0.0.1:8090)
    KARTA_E2E_USER   (default smoke-e2e)
    KARTA_E2E_PASS   (default smoke-pass-123)

Требования: сервер запущен; для LLM-шагов — доступный провайдер
(недоступность LLM не роняет смоук: печатается честная причина).
"""
import asyncio
import json
import os

import httpx
import websockets

BASE = os.getenv("KARTA_E2E_BASE", "http://127.0.0.1:8090")
USERNAME = os.getenv("KARTA_E2E_USER", "smoke-e2e")
PASSWORD = os.getenv("KARTA_E2E_PASS", "smoke-pass-123")


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        r = await c.post("/api/v1/auth/token",
                         json={"username": USERNAME, "password": PASSWORD})
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("auth: ok")

        r = await c.post("/api/v1/agents",
                         json={"name": "e2e-live-bot", "chain_id": 11155111, "tier": 1},
                         headers=headers)
        assert r.status_code == 201, r.text
        agent = r.json()
        agent_id = agent["id"]
        print("agent:", agent["tier"], agent["status"])

        r = await c.post(f"/api/v1/agents/{agent_id}/policy/from-text",
                         json={"text": "не трать больше 0.05 ETH в день"}, headers=headers)
        if r.status_code == 200 and r.json().get("dsl_yaml"):
            print("policy from-text: ok |", r.json()["summary"][:60])
            applied = await c.put(f"/api/v1/agents/{agent_id}/policy",
                                  json={"dsl_yaml": r.json()["dsl_yaml"]}, headers=headers)
            print("policy apply: v", applied.json().get("version"))
        else:
            print("policy from-text: LLM", r.status_code, r.json().get("detail", "")[:80])

        r = await c.post(f"/api/v1/agents/{agent_id}/policy/simulate",
                         json={"dsl_yaml": "limits: {per_tx_eth: 0.01, daily_eth: 5.0}\n"},
                         headers=headers)
        print("policy simulate:", r.json().get("summary"))

        r = await c.post(f"/api/v1/agents/{agent_id}/intent",
                         json={"text": "переведи 0.001 ETH на 0x1234567890abcdef1234567890abcdef12345678"},
                         headers=headers)
        if r.status_code == 200 and r.json().get("intent"):
            print("intent:", r.json()["intent"]["action"],
                  "| policy:", r.json()["policy_verdict"]["decision"])
        else:
            print("intent: LLM", r.status_code, r.json().get("detail", "")[:80])

        async with websockets.connect(
            BASE.replace("http://", "ws://").replace("https://", "wss://")
            + f"/ws?token={token}"
        ) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print("ws hello:", hello["username"])

            r = await c.post(f"/api/v1/agents/{agent_id}/start", headers=headers)
            evt = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print("ws event:", evt["type"], evt.get("status"))

            decisions = {"total": 0}
            for _ in range(8):
                await asyncio.sleep(5)
                r = await c.get(f"/api/v1/agents/{agent_id}/decisions", headers=headers)
                decisions = r.json()
                if decisions["total"] > 0:
                    break
            first = decisions["decisions"][0] if decisions.get("decisions") else {}
            print("decisions:", decisions["total"], "| action:", first.get("action"))

            drift = (await c.get(f"/api/v1/agents/{agent_id}/drift", headers=headers)).json()
            print("drift:", drift.get("level"), "| signals:", len(drift.get("signals", [])))

            if first.get("id"):
                replay = (await c.get(f"/api/v1/decisions/{first['id']}", headers=headers)).json()
                print("replay:", (replay.get("then") or {}).get("decision"),
                      "→", (replay.get("now") or {}).get("decision"),
                      "| changed:", replay.get("verdict_changed"))

            summary = (await c.get(f"/api/v1/agents/{agent_id}/reports/summary", headers=headers)).json()
            print("summary: health", summary["health"]["score"], summary["health"]["band"],
                  "| trust:", summary["trust"]["rung"])

            csv = await c.get(f"/api/v1/agents/{agent_id}/export.csv?dataset=decisions", headers=headers)
            print("csv decisions:", csv.status_code, "| lines:", len(csv.text.strip().splitlines()))

            approvals = (await c.get("/api/v1/approvals", headers=headers)).json()
            print("approvals pending:", approvals["total"])

            audit = (await c.get(f"/api/v1/agents/{agent_id}/audit", headers=headers)).json()
            print("audit events:", audit["total"],
                  "| kinds:", ",".join(e["event_type"] for e in audit["events"][:4]))

            r = await c.post(f"/api/v1/agents/{agent_id}/stop", headers=headers)
            print("stop:", r.status_code)

        # ── Модульный смоук P5/P6 (read-only + gated) ──────────────────
        print("--- модули P5/P6 ---")
        chains = (await c.get("/api/v1/chains", headers=headers)).json()
        ok_chains = sum(1 for ch in chains["chains"] if ch["health"]["status"] == "ok")
        print("chains:", f"{ok_chains}/{chains['total']} ok")

        swap_info = (await c.get("/api/v1/swap/info", headers=headers)).json()
        print("swap info:", swap_info.get("router", "")[:12] + "…", "| ready:", swap_info.get("ready"))
        quote = (await c.get("/api/v1/swap/quote?amount_in=100000000000000000&slippage_bps=50",
                             headers=headers)).json()
        print("swap quote:", "in 0.1 →", quote.get("amount_out"), "| impact", quote.get("price_impact_bps"), "bps")

        bridge_info = (await c.get("/api/v1/bridge/info", headers=headers)).json()
        print("bridge:", bridge_info.get("provider"), "| exec:", bridge_info.get("execution_enabled"))
        bq = (await c.get("/api/v1/bridge/quote?from_chain=1&to_chain=8453&amount=10000000000000000",
                          headers=headers)).json()
        print("bridge quote:", bq.get("tool_name"), "| ETA", bq.get("execution_seconds"), "s")

        aa = (await c.get("/api/v1/erc4337/info", headers=headers)).json()
        print("erc4337:", (aa.get("account") or "")[:12] + "…", "| session key:", aa.get("session_key_configured"))

        x402 = await c.get("/api/v1/x402/demo/premium")
        print("x402 challenge:", x402.status_code, "|", x402.json().get("accepts", [{}])[0].get("scheme"))

        escrow = (await c.get("/api/v1/escrow?limit=1", headers=headers)).json()
        print("escrow:", escrow.get("total"), "записей")
        ric = (await c.get("/api/v1/ricardian/agreements?limit=1", headers=headers)).json()
        print("ricardian:", ric.get("total"), "соглашений")
        reg = (await c.get(f"/api/v1/agents/{agent_id}/registry", headers=headers)).json()
        print("registry badges:", [b["id"] for b in reg.get("badges", [])])


if __name__ == "__main__":
    asyncio.run(main())
