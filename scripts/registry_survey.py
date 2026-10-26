#!/usr/bin/env python3
"""Обзор реестра MCP: что инструменты говорят о деньгах (метод из docs/REPORT-AGENT-SPEND-2026.md).

Запуск: python3 scripts/registry_survey.py [--pages 25]
Печатает числа и сохраняет snapshot.json рядом — чтобы обзор можно было повторить, а не верить.
"""

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://registry.modelcontextprotocol.io/v0/servers"
MONEY = re.compile(r"x402|usdc|stablecoin|agent wallet|wallets?\b|agent payments|"
                   r"payment rail|on-?chain payment|lightning|l402|billing|invoice")
FEATURES = {
    "budget": r"budget",
    "limit/cap": r"\blimit|\bcaps?\b",
    "kill switch": r"kill[- ]switch|emergency stop",
    "per-task": r"per[- ]task|task budget|per job",
    "receipt": r"receipt",
    "signed": r"signed|signature",
    "audit": r"audit",
    "policy": r"\bpolic",
}


def fetch(pages: int) -> list[dict]:
    cursor, out = None, []
    for _ in range(pages):
        query = {"limit": 100}
        if cursor:
            query["cursor"] = cursor
        request = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(query),
                                         headers={"User-Agent": "karta-registry-survey"})
        page = json.load(urllib.request.urlopen(request, timeout=30))
        out += [item["server"] for item in page.get("servers", [])]
        cursor = (page.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
    return out


def text(server: dict) -> str:
    return ((server.get("description") or "") + " " + (server.get("title") or "")).lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=25, help="по 100 серверов на страницу")
    args = parser.parse_args()

    servers = fetch(args.pages)
    money = [s for s in servers if MONEY.search(text(s))]

    print(f"servers: {len(servers)}")
    print(f"money-related: {len(money)}")
    for name, pattern in FEATURES.items():
        hits = sum(1 for s in money if re.search(pattern, text(s)))
        print(f"  {name:12} {hits}")

    snapshot = Path(__file__).with_name("registry_snapshot.json")
    snapshot.write_text(json.dumps(servers, ensure_ascii=False), encoding="utf-8")
    print(f"snapshot: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
