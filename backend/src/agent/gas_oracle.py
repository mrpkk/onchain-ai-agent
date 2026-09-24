"""Газ-оракул EIP-1559 (S5-04): base fee + priority → maxFeePerGas с буфером + кэш.

Источник — RPC (PublicNode и др., проверены из РФ). Честность: нет данных —
ошибка GasOracleError, никаких выдуманных значений. Кэш — TTL 15 секунд
(в пределах блока), чтобы не долбить RPC на каждый тик.

Правило капа: `ensure_within_cap()` — рекомендация выше политики (Dharma
`limits.gas_gwei_cap`) означает HOLD/отказ, а не «подкрутить лимит».
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

GWEI = 1e9


class GasOracleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class GasRecommendation:
    chain_id: int
    base_fee_gwei: float
    priority_fee_gwei: float
    max_fee_gwei: float
    block_number: int
    source: str  # base+priority | gasPrice-fallback
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "base_fee_gwei": round(self.base_fee_gwei, 3),
            "priority_fee_gwei": round(self.priority_fee_gwei, 3),
            "max_fee_gwei": round(self.max_fee_gwei, 3),
            "block_number": self.block_number,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


def ensure_within_cap(recommendation: GasRecommendation, cap_gwei: int) -> None:
    """Кап из политики: 0 = выключен. Выше капа → GasOracleError (HOLD)."""
    if cap_gwei and recommendation.max_fee_gwei > cap_gwei:
        raise GasOracleError(
            "GAS_CAP_EXCEEDED",
            f"maxFeePerGas {recommendation.max_fee_gwei:.1f} gwei > капа политики {cap_gwei} gwei",
        )


class GasOracle:
    """EIP-1559-рекомендация с кэшем. Синхронный API (вызывать из to_thread при нужде)."""

    def __init__(self, ttl_sec: int = 15, max_fee_multiplier: float = 2.0,
                 min_priority_gwei: float = 1.0):
        self.ttl_sec = ttl_sec
        self.max_fee_multiplier = max_fee_multiplier
        self.min_priority_gwei = min_priority_gwei
        self._cache: dict[int, GasRecommendation] = {}

    def recommend(self, w3, force: bool = False) -> GasRecommendation:
        """Рекомендация EIP-1559. maxFeePerGas = base×multiplier + priority (буфер ~6 блоков)."""
        try:
            chain_id = int(w3.eth.chain_id)
        except Exception as e:  # noqa: BLE001
            raise GasOracleError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

        cached = self._cache.get(chain_id)
        if cached is not None and not force:
            age = (datetime.now(timezone.utc) - cached.fetched_at).total_seconds()
            if age < self.ttl_sec:
                return cached

        try:
            block = w3.eth.get_block("latest")
            base_fee = getattr(block, "baseFeePerGas", None)
            gas_price = int(w3.eth.gas_price)
        except Exception as e:  # noqa: BLE001
            raise GasOracleError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

        if base_fee is None:
            # Сеть без EIP-1559 (или узел не отдал baseFee): честный legacy-fallback
            recommendation = GasRecommendation(
                chain_id=chain_id,
                base_fee_gwei=0.0,
                priority_fee_gwei=gas_price / GWEI,
                max_fee_gwei=gas_price / GWEI,
                block_number=int(getattr(block, "number", 0) or 0),
                source="gasPrice-fallback",
            )
            self._cache[chain_id] = recommendation
            return recommendation

        base_fee_gwei = int(base_fee) / GWEI
        try:
            priority = int(w3.eth.max_priority_fee) / GWEI
        except Exception:  # noqa: BLE001 — не все узлы поддерживают eth_maxPriorityFeePerGas
            priority = max(gas_price / GWEI - base_fee_gwei, 0.0)
        priority = max(priority, self.min_priority_gwei)

        recommendation = GasRecommendation(
            chain_id=chain_id,
            base_fee_gwei=base_fee_gwei,
            priority_fee_gwei=priority,
            max_fee_gwei=base_fee_gwei * self.max_fee_multiplier + priority,
            block_number=int(getattr(block, "number", 0) or 0),
            source="base+priority",
        )
        self._cache[chain_id] = recommendation
        return recommendation

    async def recommend_async(self, w3, force: bool = False) -> GasRecommendation:
        return await asyncio.to_thread(self.recommend, w3, force)

    def fee_fields(self, recommendation: GasRecommendation) -> dict[str, int]:
        """Поля транзакции: EIP-1559 (type 2) либо legacy gasPrice для fallback-сетей."""
        if recommendation.source == "gasPrice-fallback":
            return {"gasPrice": int(recommendation.max_fee_gwei * GWEI)}
        return {
            "type": 2,
            "maxFeePerGas": int(recommendation.max_fee_gwei * GWEI),
            "maxPriorityFeePerGas": int(recommendation.priority_fee_gwei * GWEI),
        }

    def clear_cache(self) -> None:
        self._cache.clear()


_shared: Optional[GasOracle] = None


def shared_oracle() -> GasOracle:
    """Общий оракул (кэш TTL на процесс) — не плодить RPC-запросы на каждый вызов."""
    global _shared
    if _shared is None:
        _shared = GasOracle()
    return _shared
