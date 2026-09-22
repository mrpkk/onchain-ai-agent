"""Simulation Service — обязательный preview до подписи (SPEC S3-02).

Движки: ``eth_call`` (всегда). Anvil-fork — адаптер на будущее
(``anvil_available()`` честно сообщает о недоступности).
Receipt живёт ≤120с; исполнение без свежего ``ok=True`` receipt запрещено.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import logging

logger = logging.getLogger("agent.simulation")

RECEIPT_TTL_SECONDS = 120


def anvil_available() -> bool:
    """Доступен ли anvil (Foundry) для fork-симуляций."""
    return shutil.which("anvil") is not None


@dataclass
class SimulationReceipt:
    """Квитанция симуляции. Исполнение допускается только при ok=True и свежести."""

    ok: bool
    engine: str = "eth_call"
    gas_estimate: Optional[int] = None
    revert_reason: Optional[str] = None
    state_diff: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fork_block: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = RECEIPT_TTL_SECONDS

    def is_fresh(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now - self.created_at <= timedelta(seconds=self.ttl_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "engine": self.engine,
            "gas_estimate": self.gas_estimate,
            "revert_reason": self.revert_reason,
            "state_diff": self.state_diff,
            "warnings": self.warnings,
            "fork_block": self.fork_block,
            "created_at": self.created_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }


class SimulationService:
    """Симуляция транзакций через eth_call (+ задел под anvil-fork)."""

    def __init__(self, use_anvil: bool = False):
        self.use_anvil = use_anvil and anvil_available()

    def simulate_tx(self, w3, tx: dict) -> SimulationReceipt:
        """eth_call + estimate_gas. Никаких выдумок: revert → ok=False с причиной."""
        warnings: list[str] = []
        if self.use_anvil:
            warnings.append("anvil-fork адаптер ещё не реализован — использован eth_call")
        elif anvil_available():
            warnings.append("anvil доступен, но fork-режим не включён (engine=eth_call)")
        else:
            warnings.append("anvil недоступен — engine=eth_call (state_diff пуст)")

        fork_block: Optional[int] = None
        try:
            fork_block = int(w3.eth.block_number)
        except Exception:
            pass

        try:
            w3.eth.call(tx)
        except Exception as e:  # noqa: BLE001 — revert/ошибка узла — это и есть результат
            return SimulationReceipt(
                ok=False, engine="eth_call", revert_reason=str(e)[:300],
                warnings=warnings, fork_block=fork_block,
            )

        gas_estimate: Optional[int] = None
        try:
            gas_estimate = int(w3.eth.estimate_gas(tx))
        except Exception as e:  # noqa: BLE001
            return SimulationReceipt(
                ok=False, engine="eth_call",
                revert_reason=f"estimate_gas failed: {str(e)[:250]}",
                warnings=warnings, fork_block=fork_block,
            )

        return SimulationReceipt(
            ok=True, engine="eth_call", gas_estimate=gas_estimate,
            state_diff=[], warnings=warnings, fork_block=fork_block,
        )
