"""Bridge-сервис (S5-02): кросс-чейн переводы через LI.FI (реальные маршруты).

Факты 24.09.2026 (проверено из РФ): **LI.FI доступен** и отдаёт реальные маршруты
(mainnet ETH→Base через Across, ~2 сек); Across API — тоже. Relay/Squid/Orbiter —
недоступны/нужен POST. Тестнет-маршрутов для исполнения нет (только intents с
подписью на цепочке назначения) — поэтому:

- `quote()` — реальная (read-only, бесплатно) через LI.FI;
- `status()` — реальный трекинг по tx-hash;
- `execute()` — **gated**: по умолчанию выключен (`BRIDGE_EXECUTION_ENABLED=false`)
  и отказывает `EXECUTION_DISABLED` (реальные средства/STOP-GATE), при включении —
  симуляция `eth_call` → отправка подписанного transactionRequest.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

from ..config.settings import get_settings

NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
ALLOWED_EXEC_CHAINS = {11155111, 84532, 31337}  # тестнеты для будущего исполнения


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _signer_key() -> str:
    settings = get_settings()
    key = (
        os.getenv("KARTA_BRIDGE_PRIVATE_KEY", "").strip()
        or settings.karta_ricardian_private_key.strip()
        or os.getenv("WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY", "").strip()
        or settings.wallet_metamask_eth_erc20_private_key.strip()
    )
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class BridgeService:
    def __init__(self, provider_url: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: Optional[float] = None, execution_enabled: Optional[bool] = None,
                 private_key: Optional[str] = None, transport: Optional[httpx.AsyncBaseTransport] = None):
        settings = get_settings()
        self.provider_url = (provider_url or settings.bridge_provider_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.bridge_api_key
        self.timeout = timeout or settings.bridge_timeout_seconds
        self.execution_enabled = (
            execution_enabled if execution_enabled is not None else settings.bridge_execution_enabled
        )
        self._private_key = private_key if private_key is not None else _signer_key()
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-lifi-api-key"] = self.api_key
        return headers

    async def _get(self, path: str, params: dict[str, Any]) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.provider_url, timeout=self.timeout, transport=self._transport
            ) as client:
                response = await client.get(path, params=params, headers=self._headers())
        except httpx.HTTPError as e:
            raise BridgeError("BRIDGE_UNAVAILABLE", f"Провайдер недоступен: {type(e).__name__}") from e
        if response.status_code == 404:
            raise BridgeError("NO_ROUTE", "Маршрут не найден")
        if response.status_code >= 400:
            detail = response.text[:200]
            raise BridgeError("BRIDGE_ERROR", f"Провайдер вернул {response.status_code}: {detail}")
        try:
            return response.json()
        except Exception as e:  # noqa: BLE001
            raise BridgeError("BRIDGE_ERROR", f"Некорректный ответ провайдера: {type(e).__name__}") from e

    @staticmethod
    def _normalize_quote(data: dict) -> dict:
        estimate = data.get("estimate") or {}
        action = data.get("action") or {}
        tx = data.get("transactionRequest") or {}
        fees = [
            {"name": f.get("name"), "amount_usd": f.get("amountUSD")}
            for f in (estimate.get("feeCosts") or [])
        ]
        gas = [
            {"type": g.get("type"), "amount_usd": g.get("amountUSD")}
            for g in (estimate.get("gasCosts") or [])
        ]
        return {
            "route_id": data.get("id"),
            "tool": data.get("tool"),
            "tool_name": (data.get("toolDetails") or {}).get("name"),
            "from_chain": action.get("fromChainId"),
            "to_chain": action.get("toChainId"),
            "from_token": (action.get("fromToken") or {}).get("address"),
            "to_token": (action.get("toToken") or {}).get("address"),
            "from_amount": action.get("fromAmount") or estimate.get("fromAmount"),
            "to_amount": estimate.get("toAmount"),
            "to_amount_min": estimate.get("toAmountMin"),
            "execution_seconds": estimate.get("executionDuration"),
            "fees": fees,
            "gas_costs": gas,
            "fee_usd_total": estimate.get("feeCosts", [{}]) and sum(
                float(f.get("amountUSD") or 0) for f in (estimate.get("feeCosts") or [])
            ),
            "transaction_request": {
                "to": tx.get("to"),
                "data": tx.get("data"),
                "value": tx.get("value"),
                "gas_limit": tx.get("gasLimit"),
                "chain_id": tx.get("chainId"),
            } if tx else None,
            "source": "lifi",
        }

    async def quote(self, from_chain: int, to_chain: int, amount_wei: int,
                    from_token: str = NATIVE_TOKEN, to_token: str = NATIVE_TOKEN,
                    from_address: Optional[str] = None, slippage: float = 0.005) -> dict:
        if from_chain == to_chain:
            raise BridgeError("BAD_INPUT", "from_chain и to_chain совпадают")
        if amount_wei <= 0:
            raise BridgeError("BAD_INPUT", "amount должен быть > 0")
        address = from_address or self.signer_address
        if not address:
            raise BridgeError("BAD_INPUT", "from_address обязателен (или настройте ключ)")
        params = {
            "fromChain": from_chain,
            "toChain": to_chain,
            "fromToken": from_token,
            "toToken": to_token,
            "fromAmount": str(amount_wei),
            "fromAddress": address,
            "slippage": slippage,
        }
        data = await self._get("/quote", params)
        if data.get("code") == 1002 or "message" in data and not data.get("estimate"):
            filtered = ((data.get("errors") or {}).get("filteredOut") or [])
            reason = filtered[0].get("reason") if filtered else data.get("message")
            raise BridgeError("NO_ROUTE", f"Нет доступного маршрута: {reason}")
        return self._normalize_quote(data)

    async def status(self, tx_hash: str, from_chain: int, to_chain: int) -> dict:
        params = {"txHash": tx_hash, "fromChain": from_chain, "toChain": to_chain}
        data = await self._get("/status", params)
        return {
            "status": data.get("status"),
            "substatus": data.get("substatus"),
            "sending": (data.get("sending") or {}).get("txHash"),
            "receiving": (data.get("receiving") or {}).get("txHash"),
            "tool": data.get("tool"),
            "source": "lifi",
        }

    @property
    def signer_address(self) -> Optional[str]:
        if not self._private_key:
            return None
        from eth_account import Account

        return Account.from_key(self._private_key).address

    def execute_sync(self, quote: dict) -> dict:
        """Исполнение маршрута (gated). Тестнет-only + симуляция до отправки."""
        if not self.execution_enabled:
            raise BridgeError(
                "EXECUTION_DISABLED",
                "Исполнение bridge выключено (реальные средства; STOP-GATE). "
                "Котировка и трекинг доступны без ограничений",
            )
        tx_request = quote.get("transaction_request")
        if not tx_request or not tx_request.get("to"):
            raise BridgeError("BAD_INPUT", "В котировке нет transaction_request")
        chain_id = int(tx_request.get("chain_id") or tx_request.get("chainId")
               or quote.get("from_chain") or 0)
        if chain_id not in ALLOWED_EXEC_CHAINS:
            raise BridgeError("MAINNET_FORBIDDEN", f"Исполнение bridge разрешено только в тестнете (chain {chain_id})")
        if not self._private_key:
            raise BridgeError("SIGNER_MISSING", "Ключ подписанта не настроен")

        from web3 import Web3

        settings = get_settings()
        rpc = settings.ethereum_sepolia_rpc_url if chain_id == 11155111 else settings.ethereum_rpc_url
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20.0}))
        signer = self.signer_address
        tx = {
            "from": signer,
            "to": Web3.to_checksum_address(tx_request["to"]),
            "data": tx_request.get("data") or "0x",
            "value": int(tx_request.get("value") or 0),
            "chainId": chain_id,
            "nonce": w3.eth.get_transaction_count(signer),
        }
        gas_limit = tx_request.get("gas_limit") or tx_request.get("gasLimit")
        if gas_limit:
            tx["gas"] = int(gas_limit)
        try:
            w3.eth.call(tx)
        except Exception as e:  # noqa: BLE001
            raise BridgeError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
        signed = w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        return {
            "tx_hash": tx_hash.hex(),
            "status": int(receipt.status),
            "block": int(receipt.blockNumber),
            "chain_id": chain_id,
            "route_id": quote.get("route_id"),
            "tool": quote.get("tool"),
        }

    async def execute(self, quote: dict) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(self.execute_sync, quote), 300.0)
        except BridgeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise BridgeError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def info(self) -> dict:
        return {
            "provider": self.provider_url,
            "api_key_configured": bool(self.api_key),
            "execution_enabled": self.execution_enabled,
            "signer": self.signer_address,
            "native_token": NATIVE_TOKEN,
            "supported_chains": [1, 8453, 11155111, 84532, 56, 137],
            "note": "Котировки/трекинг — реальные (LI.FI); исполнение gated (STOP-GATE реальных средств)",
        }
