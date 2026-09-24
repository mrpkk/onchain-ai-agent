"""
Perception Layer — reads blockchain data, monitors mempool, fetches oracle prices.

Provides the agent with real-time awareness of on-chain state.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .chains import CHAINS
from web3 import Web3

logger = logging.getLogger("agent.perception")


@dataclass
class TokenPrice:
    symbol: str
    price_usd: float
    timestamp: datetime
    source: str


@dataclass
class ContractState:
    address: str
    chain: str
    abi: list
    functions: dict = field(default_factory=dict)
    last_block: int = 0


@dataclass
class MempoolTx:
    hash: str
    from_address: str
    to_address: str
    value: float
    gas_price: float
    data: str
    timestamp: datetime


class BlockchainPerception:
    """Reads and monitors EVM-compatible blockchains."""

    @property
    def CHAIN_CONFIGS(self):
        """Реестр сетей (S5-07) в legacy-формате: rpc — первый (fallback — rpcs)."""
        return {
            name: {
                "rpc": cfg.rpcs[0],
                "rpcs": list(cfg.rpcs),
                "chain_id": cfg.chain_id,
                "explorer": cfg.explorer,
                "native_token": cfg.native_symbol,
                "block_time": cfg.block_time,
                "finality_blocks": cfg.finality_blocks,
            }
            for name, cfg in CHAINS.items()
        }

    def __init__(self, chains: Optional[list[str]] = None):
        self.chains = chains or ["ethereum"]
        self.connections: dict[str, Web3] = {}
        self._prices: dict[str, TokenPrice] = {}
        self._running = False
        self._initialize_connections()

    def _initialize_connections(self):
        for chain_name in self.chains:
            config = self.CHAIN_CONFIGS.get(chain_name)
            if not config:
                logger.warning(f"Unknown chain: {chain_name}")
                continue
            connected = False
            for rpc_url in config.get("rpcs", [config["rpc"]]):
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))
                    if w3.is_connected():
                        self.connections[chain_name] = w3
                        logger.info(f"Connected to {chain_name} via {rpc_url} (block #{w3.eth.block_number})")
                        connected = True
                        break
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"RPC {rpc_url} для {chain_name} недоступен: {type(e).__name__}")
            if not connected:
                logger.error(f"Failed to connect to {chain_name} (все RPC недоступны)")

    def get_web3(self, chain: str) -> Optional[Web3]:
        return self.connections.get(chain)

    def get_block_number(self, chain: str) -> int:
        w3 = self.get_web3(chain)
        return w3.eth.block_number if w3 else 0

    def get_balance(self, address: str, chain: str = "ethereum") -> float:
        w3 = self.get_web3(chain)
        if not w3:
            return 0.0
        checksum = Web3.to_checksum_address(address)
        balance_wei = w3.eth.get_balance(checksum)
        return float(Web3.from_wei(balance_wei, "ether"))

    def get_token_balance(self, token_address: str, wallet: str, chain: str = "ethereum") -> float:
        w3 = self.get_web3(chain)
        if not w3:
            return 0.0
        erc20_abi = [
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
             "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "decimals",
             "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
        ]
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=erc20_abi,
        )
        decimals = contract.functions.decimals().call()
        balance = contract.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
        return balance / (10 ** decimals)

    def get_gas_price(self, chain: str = "ethereum") -> float:
        w3 = self.get_web3(chain)
        if not w3:
            return 0.0
        gas_price = w3.eth.gas_price
        return float(Web3.from_wei(gas_price, "gwei"))

    def estimate_gas(self, tx: dict, chain: str = "ethereum") -> int:
        w3 = self.get_web3(chain)
        if not w3:
            return 0
        return w3.eth.estimate_gas(tx)

    def get_transaction_receipt(self, tx_hash: str, chain: str = "ethereum") -> Optional[dict]:
        w3 = self.get_web3(chain)
        if not w3:
            return None
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            return {
                "status": receipt["status"],
                "gas_used": receipt["gasUsed"],
                "block_number": receipt["blockNumber"],
                "logs": [dict(log) for log in receipt.get("logs", [])],
            }
        except Exception as e:
            logger.error(f"Failed to get receipt for {tx_hash}: {e}")
            return None

    def read_contract(self, address: str, abi: list, function_name: str,
                      args: list = None, chain: str = "ethereum") -> any:
        w3 = self.get_web3(chain)
        if not w3:
            return None
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=abi,
        )
        func = contract.functions[function_name](*(args or []))
        return func.call()

    def get_contract_events(self, address: str, abi: list, event_name: str,
                            from_block: int = 0, chain: str = "ethereum") -> list:
        w3 = self.get_web3(chain)
        if not w3:
            return []
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(address),
            abi=abi,
        )
        event = getattr(contract.events, event_name)
        logs = event.get_logs(fromBlock=from_block)
        return [dict(log) for log in logs]


class PriceOracle:
    """Fetches token prices from public APIs (CoinGecko, no API key needed)."""

    COINGECKO_API = "https://api.coingecko.com/api/v3"

    async def get_price(self, token_ids: list[str] = None) -> dict[str, TokenPrice]:
        token_ids = token_ids or ["bitcoin", "ethereum", "solana"]
        coins = ",".join(token_ids)
        url = f"{self.COINGECKO_API}/simple/price?ids={coins}&vs_currencies=usd&include_24hr_change=true"

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        prices = {}
                        for token_id, info in data.items():
                            prices[token_id] = TokenPrice(
                                symbol=token_id.upper(),
                                price_usd=info.get("usd", 0),
                                timestamp=datetime.now(timezone.utc),
                                source="coingecko",
                            )
                        return prices
        except Exception as e:
            logger.error(f"Price fetch error: {e}")
        return {}

    async def get_trending(self) -> list[dict]:
        url = f"{self.COINGECKO_API}/search/trending"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("coins", [])[:10]
        except Exception as e:
            logger.error(f"Trending fetch error: {e}")
        return []


class MempoolMonitor:
    """Реальный монитор блоков: фильтрация tx по watch-адресам + газ-тренд.

    Честность (SPEC S2-07): при недоступном RPC scan_once возвращает
    ``{"ok": False, "reason": "rpc_unavailable"}`` — никаких выдуманных tx.
    """

    def __init__(self, blockchain: "BlockchainPerception", history: int = 20):
        self.blockchain = blockchain
        self._watched_addresses: set[str] = set()
        self._gas_history: list[tuple[int, float]] = []  # (block, gwei)
        self._recent: list[MempoolTx] = []
        self._history_limit = history
        self._running = False
        self._last_block: Optional[int] = None
        self.blocks_scanned = 0

    # ── watch-список ────────────────────────────────────────────────

    def watch(self, address: str):
        self._watched_addresses.add(Web3.to_checksum_address(address))

    def unwatch(self, address: str):
        self._watched_addresses.discard(Web3.to_checksum_address(address))

    # ── газ-тренд ───────────────────────────────────────────────────

    def gas_trend(self) -> str:
        """up | down | flat | unknown — по истории baseFee (треть к трети)."""
        if len(self._gas_history) < 3:
            return "unknown"
        values = [gwei for _, gwei in self._gas_history]
        third = max(1, len(values) // 3)
        first_avg = sum(values[:third]) / third
        last_avg = sum(values[-third:]) / third
        if first_avg == 0:
            return "unknown"
        change = (last_avg - first_avg) / first_avg
        if change > 0.10:
            return "up"
        if change < -0.10:
            return "down"
        return "flat"

    def status(self) -> dict:
        return {
            "implemented": True,
            "running": self._running,
            "watched_addresses": len(self._watched_addresses),
            "blocks_scanned": self.blocks_scanned,
            "gas_trend": self.gas_trend(),
            "recent_matched": len(self._recent),
            "last_block": self._last_block,
        }

    # ── сканирование ────────────────────────────────────────────────

    def _block_gas_gwei(self, w3: Web3, block: dict) -> float:
        base_fee = block.get("baseFeePerGas")
        if base_fee is None:
            try:
                base_fee = w3.eth.gas_price
            except Exception:
                return 0.0
        return float(Web3.from_wei(int(base_fee), "gwei"))

    def _match_tx(self, tx: dict, block_number: int, gas_gwei: float) -> Optional[MempoolTx]:
        sender = (tx.get("from") or "").lower()
        receiver = (tx.get("to") or "").lower()
        watched = {addr.lower() for addr in self._watched_addresses}
        if sender not in watched and receiver not in watched:
            return None
        return MempoolTx(
            hash=tx.get("hash", "").hex() if hasattr(tx.get("hash", ""), "hex") else str(tx.get("hash", "")),
            from_address=tx.get("from", "") or "",
            to_address=tx.get("to", "") or "",
            value=float(Web3.from_wei(int(tx.get("value", 0) or 0), "ether")),
            gas_price=gas_gwei,
            data=(tx.get("input", "") or "")[:68] if isinstance(tx.get("input", ""), str) else "",
            timestamp=datetime.now(timezone.utc),
        )

    async def scan_once(self, chain: str = "ethereum") -> dict:
        """Один проход по новым блокам. Честный отказ при недоступном RPC."""
        w3 = self.blockchain.get_web3(chain)
        if not w3:
            return {"ok": False, "reason": "rpc_unavailable", "found": [], "scanned_blocks": 0}

        try:
            current_block = int(w3.eth.block_number)
        except Exception as e:
            return {"ok": False, "reason": f"rpc_error: {type(e).__name__}", "found": [],
                    "scanned_blocks": 0}

        if self._last_block is None:
            # первый проход: обрабатываем текущий блок (fresh-старт)
            self._last_block = max(current_block - 1, 0)
        found: list[MempoolTx] = []
        scanned = 0
        for block_number in range(self._last_block + 1, current_block + 1):
            try:
                block = w3.eth.get_block(block_number, full_transactions=True)
            except Exception as e:
                logger.warning("Mempool: блок %s не прочитан: %s", block_number, e)
                break
            gas_gwei = self._block_gas_gwei(w3, block)
            self._gas_history.append((block_number, gas_gwei))
            self._gas_history = self._gas_history[-self._history_limit:]
            for tx in block.get("transactions", []):
                matched = self._match_tx(tx, block_number, gas_gwei)
                if matched is not None:
                    found.append(matched)
                    self._recent.append(matched)
            scanned += 1

        self._recent = self._recent[-self._history_limit:]
        self._last_block = current_block
        self.blocks_scanned += scanned
        return {"ok": True, "reason": None, "scanned_blocks": scanned,
                "found": [tx.__dict__ for tx in found]}

    async def start_monitoring(self, chain: str = "ethereum", interval: int = 12):
        self._running = True
        while self._running:
            result = await self.scan_once(chain)
            if not result["ok"] and result["reason"] == "rpc_unavailable":
                logger.warning("Mempool: RPC %s недоступен — мониторинг ждёт", chain)
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False
