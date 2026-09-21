"""Отчёты KARTA (SPEC S4-07): сводка и CSV-экспорт (decisions/transactions/audit).

Честность: realized/unrealized PnL требует исполненных сделок и ценовых данных
(Phase 5) — до этого summary отдаёт realized_pnl=None + причину. Газ считается
из реальных полей transactions (native units, без выдуманных USD-курсов).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Agent, DecisionRepository, PolicyRepository, TransactionRepository
from ..security.dharma import compile_yaml
from .tiers import tier_simulation_mode, trust_ladder_rung

__all__ = ["build_summary", "decisions_csv", "transactions_csv"]


async def build_summary(session: AsyncSession, agent_id: uuid.UUID) -> dict:
    decisions_count = await DecisionRepository(session).count_for_agent(agent_id)
    txs = await TransactionRepository(session).list_for_agent(agent_id, limit=1000)
    gas_eth = sum((t.gas_used or 0) * (t.gas_price_gwei or 0.0) for t in txs) / 1e9
    confirmed = sum(1 for t in txs if t.status == "confirmed")
    agent_row = await session.get(Agent, agent_id)
    policy_row = await PolicyRepository(session).get_active(agent_id)
    undo_window = 0
    approvals_amount = 0.0
    if policy_row is not None:
        try:
            compiled = compile_yaml(policy_row.dsl_yaml)
            undo_window = compiled.model.undo.window_seconds
            approvals_amount = compiled.model.approvals.required_if.amount_eth_gte
        except Exception:  # noqa: BLE001 — политика не должна ломать отчёт
            pass
    trust = trust_ladder_rung(
        int(getattr(agent_row, "tier", 0) or 0),
        simulation_mode=tier_simulation_mode(int(getattr(agent_row, "tier", 0) or 0)),
        undo_window_seconds=undo_window,
        approvals_amount_eth=approvals_amount,
    )
    return {
        "agent_id": str(agent_id),
        "trust": trust,
        "decisions_count": decisions_count,
        "transactions_count": len(txs),
        "transactions_confirmed": confirmed,
        "gas_spent_eth": round(gas_eth, 9),
        "realized_pnl": None,
        "unrealized_pnl": None,
        "pnl_available": False,
        "pnl_reason": "нет исполненных сделок и ценовых данных (Phase 5)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def decisions_csv(rows: Sequence) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "action", "risk_level", "confidence",
                     "status", "requires_approval", "reasoning"])
    for row in rows:
        writer.writerow([
            str(row.id),
            row.created_at.isoformat() if row.created_at else "",
            row.action,
            row.risk_level or "",
            row.confidence if row.confidence is not None else "",
            row.status or "",
            "true" if row.requires_approval else "false",
            (row.reasoning or "").replace("\n", " ")[:300],
        ])
    return buffer.getvalue()


def transactions_csv(rows: Sequence) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "status", "chain_id", "action", "tx_hash",
                     "gas_used", "gas_price_gwei", "error"])
    for row in rows:
        writer.writerow([
            str(row.id),
            row.created_at.isoformat() if row.created_at else "",
            row.status or "",
            row.chain_id or "",
            row.action or "",
            row.tx_hash or "",
            row.gas_used if row.gas_used is not None else "",
            row.gas_price_gwei if row.gas_price_gwei is not None else "",
            (row.error or "").replace("\n", " ")[:200],
        ])
    return buffer.getvalue()
