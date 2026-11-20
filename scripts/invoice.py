#!/usr/bin/env python3
"""CLI USDC-инвойса KARTA — без провайдера и без KYC.

    python3 scripts/invoice.py create --amount 2500 --memo "KARTA pilot"
    python3 scripts/invoice.py show inv_...
    python3 scripts/invoice.py verify inv_... --tx 0x...

Адрес получателя берётся только из ~/.env (KARTA_USDC_ADDRESS или
WALLET_BINANCE_USDC_BASE). Счёт не считает себя оплаченным, пока сеть не
подтвердит сумму.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.billing import usdc_invoice as inv  # noqa: E402


def _load_env_file() -> None:
    """Адрес получателя — только из ~/.env. Строки с `source` ломаются, поэтому
    читаем простым парсером и не трогаем уже заданные переменные."""
    path = Path.home() / ".env"
    if not path.exists():
        return
    import os
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in inv.ADDRESS_ENVS and not os.environ.get(key):
            os.environ[key] = value.strip().strip('"').strip("'")


def main() -> int:
    parser = argparse.ArgumentParser(description="USDC invoice (Base, no PSP)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create")
    create.add_argument("--amount", required=True, help="USDC, e.g. 2500")
    create.add_argument("--memo", default="")
    create.add_argument("--ttl-hours", type=int, default=72)

    show = sub.add_parser("show")
    show.add_argument("invoice_id")

    verify = sub.add_parser("verify")
    verify.add_argument("invoice_id")
    verify.add_argument("--tx", required=True, help="transaction hash on Base")

    args = parser.parse_args()
    _load_env_file()
    try:
        if args.cmd == "create":
            print(json.dumps(inv.create(args.amount, args.memo, args.ttl_hours),
                             ensure_ascii=False, indent=1))
        elif args.cmd == "show":
            item = inv.get(args.invoice_id)
            print(json.dumps(item, ensure_ascii=False, indent=1) if item else "not found")
            return 0 if item else 1
        else:
            item = inv.verify(args.invoice_id, args.tx)
            print(json.dumps(item, ensure_ascii=False, indent=1))
            return 0 if item.get("status") == "paid" else 1
    except (KeyError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
