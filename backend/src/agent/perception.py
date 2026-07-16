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

from web3 import Web3
from web3.middleware import geth_poa_middleware

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

    CHAIN_CONFIGS = {
        "ethereum": {
            "rpc": "https://eth.llamarpc.com",
            "chain_id": 1,
            "explorer": "https://etherscan.io",
            "native_token": "ETH",
            "block_time": 12,
        },
        "bsc": {
            "rpc": "https://bsc-dataseed.binance.org",
            "chain_id": 56,
            "explorer": "https://bscscan.com",
            "native_token": "BNB",
            "block_time": 3,
        },
        "polygon": {
            "rpc": "https://polygon-rpc.com",
            "chain_id": 137,
            "explorer": "https://polygonscan.com",
            "native_token": "MATIC",
            "block_time": 2,
        },
        "sepolia": {
            "rpc": "https://rpc.sepolia.org",
            "chain_id": 11155111,
            "explorer": "https://sepolia.etherscan.io",
            "native_token": "ETH",
            "block_time": 12,
        },
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
            try:
                w3 = Web3(Web3.HTTPProvider(config["rpc"]))
                try:
                    w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                except Exception:
                    pass
                if w3.is_connected():
                    self.connections[chain_name] = w3
                    logger.info(f"Connected to {chain_name} (block #{w3.eth.block_number})")
                else:
                    logger.error(f"Failed to connect to {chain_name}")
            except Exception as e:
                logger.error(f"Connection error for {chain_name}: {e}")

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
    """Monitors pending transactions in the mempool."""

    def __init__(self, blockchain: BlockchainPerception):
        self.blockchain = blockchain
        self._watched_addresses: set[str] = set()
        self._running = False

    def watch(self, address: str):
        self._watched_addresses.add(Web3.to_checksum_address(address))

    def unwatch(self, address: str):
        self._watched_addresses.discard(Web3.to_checksum_address(address))

    async def start_monitoring(self, chain: str = "ethereum", interval: int = 12):
        self._running = True
        w3 = self.blockchain.get_web3(chain)
        if not w3:
            return

        last_block = w3.eth.block_number
        logger.info(f"Starting mempool monitor on {chain} from block {last_block}")

        while self._running:
            try:
                current_block = w3.eth.block_number
                if current_block > last_block:
                    for tx_num in range(w3.eth.get_block(current_block).get("transactions", []) and
                                        len(w3.eth.get_block(current_block, full_transactions=True).get("transactions", []))):
                        pass
                    last_block = current_block
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Mempool monitor error: {e}")
                await asyncio.sleep(interval)

    def stop(self):
        self._running = False
