#!/usr/bin/env python3
"""karta-audit-export — экспорт Sakshi Log (SPEC S2-02).

Использование:
    python scripts/karta_audit_export.py --format json [--agent-id UUID] [--out FILE]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import session_scope  # noqa: E402
from src.security.sakshi import SakshiLog  # noqa: E402


async def _export(fmt: str, agent_id: uuid.UUID | None, out: str | None) -> None:
    log = SakshiLog()
    async with session_scope() as session:
        events = await log.list_events(session, agent_id=agent_id)
        data = log.export_json(events) if fmt == "json" else log.export_csv(events)
    if out:
        Path(out).write_text(data, encoding="utf-8")
        print(f"Экспортировано событий: {len(events)} → {out}")
    else:
        print(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Экспорт аудит-журнала KARTA (Sakshi Log)")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    parser.add_argument("--agent-id", default=None, help="UUID агента (опционально)")
    parser.add_argument("--out", default=None, help="Файл для записи (иначе stdout)")
    args = parser.parse_args()
    agent_id = uuid.UUID(args.agent_id) if args.agent_id else None
    asyncio.run(_export(args.format, agent_id, args.out))


if __name__ == "__main__":
    main()
