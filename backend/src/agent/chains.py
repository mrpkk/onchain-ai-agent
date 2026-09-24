"""Реестр сетей (S5-07): сеть = config {rpcs[], explorer, finality, health}.

RPC-списки — с fallback по порядку, проверены из РФ живьём (24.09.2026):
PublicNode/DRPC/1RPC/Base.org работают; llamarpc, rpc.sepolia.org, polygon-rpc.com — нет.

`finality_blocks` — эвристика для политик/UI (не юридическая финальность):
ETH — 2 эпохи (64 блока), Base (OP-stack) — safe-head через L1 (2000), BSC — ~15, Polygon — 128.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Union

GWEI = 1e9


@dataclass(frozen=True)
class ChainConfig:
    chain_id: int
    name: str
    rpcs: tuple[str, ...]
    explorer: str
    native_symbol: str
    block_time: float
    finality_blocks: int
    eip1559: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "rpcs": list(self.rpcs),
            "explorer": self.explorer,
            "native_symbol": self.native_symbol,
            "block_time": self.block_time,
            "finality_blocks": self.finality_blocks,
            "eip1559": self.eip1559,
        }


CHAINS: dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        chain_id=1, name="ethereum",
        rpcs=("https://ethereum-rpc.publicnode.com", "https://eth.drpc.org", "https://1rpc.io/eth"),
        explorer="https://etherscan.io", native_symbol="ETH", block_time=12.0, finality_blocks=64,
    ),
    "sepolia": ChainConfig(
        chain_id=11155111, name="sepolia",
        rpcs=("https://ethereum-sepolia-rpc.publicnode.com", "https://1rpc.io/sepolia"),
        explorer="https://sepolia.etherscan.io", native_symbol="ETH", block_time=12.0,
        finality_blocks=12,
    ),
    "base": ChainConfig(
        chain_id=8453, name="base",
        rpcs=("https://base-rpc.publicnode.com", "https://mainnet.base.org"),
        explorer="https://basescan.org", native_symbol="ETH", block_time=2.0, finality_blocks=2000,
    ),
    "base_sepolia": ChainConfig(
        chain_id=84532, name="base_sepolia",
        rpcs=("https://base-sepolia-rpc.publicnode.com", "https://sepolia.base.org"),
        explorer="https://sepolia.basescan.org", native_symbol="ETH", block_time=2.0,
        finality_blocks=2000,
    ),
    "bsc": ChainConfig(
        chain_id=56, name="bsc",
        rpcs=("https://bsc-rpc.publicnode.com", "https://bsc-dataseed.binance.org"),
        explorer="https://bscscan.com", native_symbol="BNB", block_time=3.0, finality_blocks=15,
    ),
    "polygon": ChainConfig(
        chain_id=137, name="polygon",
        rpcs=("https://polygon-bor-rpc.publicnode.com",),
        explorer="https://polygonscan.com", native_symbol="POL", block_time=2.0,
        finality_blocks=128,
    ),
}

CHAIN_BY_ID: dict[int, ChainConfig] = {cfg.chain_id: cfg for cfg in CHAINS.values()}


def get_chain(name_or_id: Union[str, int]) -> Optional[ChainConfig]:
    if isinstance(name_or_id, int):
        return CHAIN_BY_ID.get(name_or_id)
    return CHAINS.get(str(name_or_id).lower())


# ── health (probe с TTL-кэшем) ───────────────────────────────────────

@dataclass
class ChainHealth:
    chain: str
    chain_id: int
    status: str  # ok | down
    rpc_used: Optional[str] = None
    block_number: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "chain_id": self.chain_id,
            "status": self.status,
            "rpc_used": self.rpc_used,
            "block_number": self.block_number,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "checked_at": self.checked_at.isoformat(),
        }


def _probe_rpc(rpc_url: str, timeout: float = 5.0) -> tuple[Optional[int], Optional[str], int]:
    """Один RPC-пробник: (block_number, error, latency_ms)."""
    from web3 import Web3

    started = time.monotonic()
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
        block = int(w3.eth.block_number)
        return block, None, int((time.monotonic() - started) * 1000)
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__, int((time.monotonic() - started) * 1000)


class ChainHealthCache:
    """Пробует RPC по порядку (первый рабочий побеждает), кэширует результат TTL."""

    def __init__(self, ttl_sec: int = 60):
        self.ttl_sec = ttl_sec
        self._cache: dict[str, ChainHealth] = {}

    def probe(self, chain: str, force: bool = False) -> ChainHealth:
        config = get_chain(chain)
        if config is None:
            raise KeyError(f"Неизвестная сеть: {chain}")

        cached = self._cache.get(chain)
        if cached is not None and not force:
            age = (datetime.now(timezone.utc) - cached.checked_at).total_seconds()
            if age < self.ttl_sec:
                return cached

        last_error = None
        for rpc_url in config.rpcs:
            block, error, latency = _probe_rpc(rpc_url)
            if error is None:
                health = ChainHealth(
                    chain=chain, chain_id=config.chain_id, status="ok",
                    rpc_used=rpc_url, block_number=block, latency_ms=latency,
                )
                self._cache[chain] = health
                return health
            last_error = f"{rpc_url}: {error}"

        health = ChainHealth(
            chain=chain, chain_id=config.chain_id, status="down", error=last_error
        )
        self._cache[chain] = health
        return health

    async def probe_async(self, chain: str, force: bool = False) -> ChainHealth:
        return await asyncio.to_thread(self.probe, chain, force)

    def clear(self) -> None:
        self._cache.clear()


_shared_cache: Optional[ChainHealthCache] = None


def shared_health() -> ChainHealthCache:
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = ChainHealthCache()
    return _shared_cache
