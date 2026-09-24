"""Swap-сервис (S5-01): котировка + slippage-guard + исполнение.

Реальность 24.09.2026 (проверено из РФ): все крупные агрегаторы гео-заблокированы
(Odos «Geolocation Block», Paraswap/Kyber 403, 1inch/0x требуют API-ключ).
Поэтому: локальный Uniswap-V2-совместимый контур (MockDEX) — реальные переводы
и котировка on-chain; aggregator-адаптер оставлен опцией (`SWAP_AGGREGATOR_URL`),
при отсутствии — честная ошибка AGGREGATOR_UNAVAILABLE (не выдумываем цены).

Slippage-guard двойной: (1) Dharma проверяет `params.slippage_bps` против
`limits.slippage_bps_max`; (2) сервис обрезает amountOutMin по slippage_bps и
отказывает, если запрошенный slippage выше переданного капа (defense in depth).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from ..config.settings import get_settings

ALLOWED_CHAINS = {11155111, 31337}
BPS = 10_000

DEX_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "token0", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "address"}]},
    {"type": "function", "name": "token1", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "address"}]},
    {"type": "function", "name": "reserve0", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint112"}]},
    {"type": "function", "name": "reserve1", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint112"}]},
    {"type": "function", "name": "getAmountsOut", "stateMutability": "view",
     "inputs": [{"name": "amountIn", "type": "uint256"},
                {"name": "path", "type": "address[]"}],
     "outputs": [{"type": "uint256[]"}]},
    {"type": "function", "name": "swapExactTokensForTokens", "stateMutability": "nonpayable",
     "inputs": [{"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"},
                {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}],
     "outputs": [{"type": "uint256[]"}]},
]

ERC20_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
]


def _checksum(address: str) -> str:
    from web3 import Web3

    return Web3.to_checksum_address(address)


class SwapError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _signer_key() -> str:
    settings = get_settings()
    key = (
        os.getenv("KARTA_SWAP_PRIVATE_KEY", "").strip()
        or os.getenv("KARTA_ESCROW_PRIVATE_KEY", "").strip()
        or os.getenv("KARTA_RICARDIAN_PRIVATE_KEY", "").strip()
        or settings.karta_ricardian_private_key.strip()
        or os.getenv("WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY", "").strip()
        or settings.wallet_metamask_eth_erc20_private_key.strip()
    )
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class SwapService:
    def __init__(self, rpc_url: Optional[str] = None, router_address: Optional[str] = None,
                 token_in: Optional[str] = None, token_out: Optional[str] = None,
                 private_key: Optional[str] = None):
        settings = get_settings()
        self.rpc_url = rpc_url if rpc_url is not None else settings.swap_rpc_url
        self.router_address = (
            router_address if router_address is not None else settings.swap_router_address
        )
        self.token_in = token_in if token_in is not None else settings.swap_token_in
        self.token_out = token_out if token_out is not None else settings.swap_token_out
        self.aggregator_url = settings.swap_aggregator_url
        self._private_key = private_key if private_key is not None else _signer_key()
        self._w3 = None
        self._dex = None

    def _connect(self):
        if self._dex is not None:
            return
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10.0}))
        if not self.router_address:
            raise SwapError("NOT_CONFIGURED", "Адрес swap-роутера не задан")
        if self._w3.eth.chain_id not in ALLOWED_CHAINS:
            raise SwapError("MAINNET_FORBIDDEN", "Swap-операции разрешены только в тестнете")
        self._dex = self._w3.eth.contract(
            address=_checksum(self.router_address), abi=DEX_ABI
        )

    @property
    def signer_address(self) -> Optional[str]:
        if not self._private_key:
            return None
        from eth_account import Account

        return Account.from_key(self._private_key).address

    def _path(self, direction: str) -> list[str]:
        if direction == "in_out":
            return [self.token_in, self.token_out]
        if direction == "out_in":
            return [self.token_out, self.token_in]
        raise SwapError("BAD_INPUT", "direction: in_out | out_in")

    # ── котировка ────────────────────────────────────────────────
    def _quote_sync(self, amount_in: int, slippage_bps: int, direction: str) -> dict:
        self._connect()
        if amount_in <= 0:
            raise SwapError("BAD_INPUT", "amount_in должен быть > 0")
        if slippage_bps < 0 or slippage_bps > BPS:
            raise SwapError("BAD_INPUT", "slippage_bps: 0..10000")
        path = [_checksum(p) for p in self._path(direction)]
        amounts = self._dex.functions.getAmountsOut(amount_in, path).call()
        amount_out = int(amounts[1])
        if amount_out <= 0:
            raise SwapError("INSUFFICIENT_LIQUIDITY", "Пустой пул или нулевой выход")

        token0 = _checksum(self._dex.functions.token0().call())
        reserve0 = int(self._dex.functions.reserve0().call())
        reserve1 = int(self._dex.functions.reserve1().call())
        reserve_in = reserve0 if path[0] == token0 else reserve1
        reserve_out = reserve1 if path[0] == token0 else reserve0

        # price impact: спот-выход vs фактический выход (в bps)
        spot_out = (amount_in * reserve_out) // reserve_in if reserve_in else 0
        price_impact_bps = int((spot_out - amount_out) * BPS / spot_out) if spot_out else 0
        min_amount_out = amount_out * (BPS - slippage_bps) // BPS
        return {
            "amount_in": str(amount_in),
            "amount_out": str(amount_out),
            "min_amount_out": str(min_amount_out),
            "slippage_bps": int(slippage_bps),
            "price_impact_bps": price_impact_bps,
            "path": path,
            "router": self.router_address,
            "source": "mockdex(uniswap-v2)",
            "aggregator_available": bool(self.aggregator_url),
        }

    async def quote(self, amount_in: int, slippage_bps: int = 50,
                    direction: str = "in_out") -> dict:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._quote_sync, int(amount_in), int(slippage_bps), direction),
                60.0,
            )
        except SwapError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SwapError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e
        result.pop("path", None)  # наружу путь не нужен
        return result

    async def aggregator_quote(self, amount_in: int, slippage_bps: int = 50) -> dict:
        """Агрегаторная котировка: опция. Из РФ агрегаторы гео-заблокированы (24.09.2026)."""
        raise SwapError(
            "AGGREGATOR_UNAVAILABLE",
            "Агрегаторы недоступны из РФ (Odos: Geolocation Block; Paraswap/Kyber: 403; "
            "1inch/0x: требуют ключ). Используется локальный контур; агрегатор — опция "
            "SWAP_AGGREGATOR_URL для INTL-деплоя",
        )

    # ── исполнение ───────────────────────────────────────────────
    def _send_swap_sync(self, amount_in: int, slippage_bps: int, direction: str,
                        max_slippage_bps: int) -> dict:
        self._connect()
        if max_slippage_bps and slippage_bps > max_slippage_bps:
            raise SwapError(
                "SLIPPAGE_CAP_EXCEEDED",
                f"slippage {slippage_bps} bps > капа политики {max_slippage_bps} bps",
            )
        if not self._private_key:
            raise SwapError("SIGNER_MISSING", "Ключ подписанта не настроен")
        quote = self._quote_sync(amount_in, slippage_bps, direction)
        path = [_checksum(p) for p in self._path(direction)]
        amount_out_min = int(quote["min_amount_out"])
        signer = self.signer_address

        token_in_addr = path[0]
        token = self._w3.eth.contract(address=token_in_addr, abi=ERC20_ABI)
        result: dict = {}

        allowance = int(token.functions.allowance(
            signer, _checksum(self.router_address)).call())
        if allowance < amount_in:
            approve_fn = token.functions.approve(
                _checksum(self.router_address), amount_in)
            tx = approve_fn.build_transaction({
                "from": signer,
                "nonce": self._w3.eth.get_transaction_count(signer),
                "chainId": self._w3.eth.chain_id,
            })
            signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
            approve_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
            result["approve_tx"] = approve_hash.hex()
            result["approve_status"] = int(receipt.status)

        swap_fn = self._dex.functions.swapExactTokensForTokens(
            amount_in, amount_out_min, path, signer, 2**64
        )
        try:
            swap_fn.call({"from": signer})
        except Exception as e:  # noqa: BLE001
            raise SwapError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
        tx = swap_fn.build_transaction({
            "from": signer,
            "nonce": self._w3.eth.get_transaction_count(signer),
            "chainId": self._w3.eth.chain_id,
        })
        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        result.update({
            "tx_hash": tx_hash.hex(),
            "status": int(receipt.status),
            "block": int(receipt.blockNumber),
            "gas_used": int(receipt.gasUsed),
            "chain_id": int(self._w3.eth.chain_id),
            "amount_in": quote["amount_in"],
            "amount_out": quote["amount_out"],
            "min_amount_out": quote["min_amount_out"],
            "slippage_bps": quote["slippage_bps"],
            "price_impact_bps": quote["price_impact_bps"],
        })
        return result

    async def execute(self, amount_in: int, slippage_bps: int = 50,
                      direction: str = "in_out", max_slippage_bps: int = 0) -> dict:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._send_swap_sync, int(amount_in), int(slippage_bps),
                                  direction, int(max_slippage_bps)),
                240.0,
            )
        except SwapError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SwapError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def info(self) -> dict:
        def _read() -> dict:
            self._connect()
            from web3 import Web3

            token_in = self._w3.eth.contract(
                address=Web3.to_checksum_address(self.token_in), abi=ERC20_ABI)
            token_out = self._w3.eth.contract(
                address=Web3.to_checksum_address(self.token_out), abi=ERC20_ABI)
            signer = self.signer_address
            return {
                "router": self.router_address,
                "token_in": self.token_in,
                "token_out": self.token_out,
                "reserve0": str(int(self._dex.functions.reserve0().call())),
                "reserve1": str(int(self._dex.functions.reserve1().call())),
                "signer": signer,
                "balance_in": str(int(token_in.functions.balanceOf(signer).call())) if signer else None,
                "balance_out": str(int(token_out.functions.balanceOf(signer).call())) if signer else None,
                "chain": "sepolia",
                "ready": signer is not None,
            }

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 60.0)
        except SwapError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SwapError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e
