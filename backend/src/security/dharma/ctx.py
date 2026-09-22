"""Контекст оценки Dharma — вход для чистого evaluator (SPEC S1-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TxContext:
    """Всё, что нужно для детерминированной оценки действия (без LLM)."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    chain_id: int | None = None
    gas_price_gwei: float = 0.0
    now_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    spent_today_eth: float = 0.0
    recent_tx: list[datetime] = field(default_factory=list)
    anomaly_score: float = 0.0
    revert_streak: int = 0
    risk_score: float = 0.0
    new_spender: bool = False

    def value_eth(self) -> float:
        """Оценка стоимости действия в ETH (transfer → amount, иначе value)."""
        if self.action == "transfer":
            return float(self.params.get("amount") or 0)
        return float(self.params.get("value") or 0)

    def addresses(self) -> list[str]:
        """Все адреса-участники действия (lowercase)."""
        out: list[str] = []
        for key in ("to", "spender", "token", "address", "contract"):
            value = self.params.get(key)
            if value:
                out.append(str(value).lower())
        return out
