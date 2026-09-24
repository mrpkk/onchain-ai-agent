"""x402-демо (S6-05): 402-челлендж → EIP-3009-подпись → верификация → сеттлмент.

Демо-режим (тестнет-only): собственный тестнет-токен xUSDC без ценности.
Сервер сам верифицирует EIP-712-подпись и отправляет `transferWithAuthorization`
(газ сервера). Реальный приём платежей (INTL-профиль) — отдельное решение (STOP-GATE).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any, Optional

from ..config.settings import get_settings

ALLOWED_CHAINS = {11155111, 31337}
X402_VERSION = 1
NETWORK = "sepolia"
ASSET_NAME = "x402 Demo USD"
ASSET_VERSION = "1"

TOKEN_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "authorizationState", "stateMutability": "view",
     "inputs": [{"name": "authorizer", "type": "address"},
                {"name": "nonce", "type": "bytes32"}],
     "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "transferWithAuthorization", "stateMutability": "nonpayable",
     "inputs": [{"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
                {"name": "v", "type": "uint8"},
                {"name": "r", "type": "bytes32"},
                {"name": "s", "type": "bytes32"}],
     "outputs": []},
]


class X402Error(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _signer_key() -> str:
    settings = get_settings()
    key = (
        os.getenv("KARTA_X402_PRIVATE_KEY", "").strip()
        or os.getenv("WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY", "").strip()
        or settings.wallet_metamask_eth_erc20_private_key.strip()
    )
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class X402Service:
    def __init__(self, rpc_url: Optional[str] = None, token_address: Optional[str] = None,
                 pay_to: Optional[str] = None, price_wei: Optional[int] = None,
                 private_key: Optional[str] = None):
        settings = get_settings()
        self.rpc_url = rpc_url if rpc_url is not None else settings.x402_rpc_url
        self.token_address = (
            token_address if token_address is not None else settings.x402_token_address
        )
        self._private_key = private_key if private_key is not None else _signer_key()
        self._pay_to = pay_to
        self.price_wei = price_wei if price_wei is not None else settings.x402_price_wei
        self._w3 = None
        self._token = None

    @property
    def pay_to(self) -> Optional[str]:
        if self._pay_to:
            return self._pay_to
        if not self._private_key:
            return None
        from eth_account import Account

        return Account.from_key(self._private_key).address

    def _connect(self):
        if self._token is not None:
            return
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10.0}))
        if not self.token_address:
            raise X402Error("NOT_CONFIGURED", "x402-токен не задан")
        if self._w3.eth.chain_id not in ALLOWED_CHAINS:
            raise X402Error("MAINNET_FORBIDDEN", "x402-демо разрешено только в тестнете")
        self._token = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self.token_address), abi=TOKEN_ABI
        )

    # ── 402-челлендж ─────────────────────────────────────────────
    def payment_requirements(self, resource: str) -> dict:
        if not self.token_address or not self.pay_to:
            raise X402Error("NOT_CONFIGURED", "x402-демо не настроено (токен/pay_to)")
        return {
            "x402Version": X402_VERSION,
            "accepts": [{
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": str(self.price_wei),
                "resource": resource,
                "description": "KARTA demo premium resource (x402, testnet only)",
                "mimeType": "application/json",
                "payTo": self.pay_to,
                "maxTimeoutSeconds": 300,
                "asset": self.token_address,
                "extra": {"name": ASSET_NAME, "version": ASSET_VERSION, "demo": True},
            }],
            "demo": True,
            "note": (
                "Тестнет-демо x402: реальные платежи отключены (STOP-GATE); "
                "токен xUSDC не имеет ценности"
            ),
        }

    # ── верификация подписи (локально, без facilitator) ──────────
    def _decode_header(self, payment_header: str) -> dict:
        try:
            raw = base64.b64decode(payment_header, validate=True)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise X402Error("INVALID_PAYMENT", f"X-PAYMENT не декодируется: {type(e).__name__}") from e
        if payload.get("x402Version") != X402_VERSION:
            raise X402Error("INVALID_PAYMENT", "x402Version не поддерживается")
        if payload.get("scheme") != "exact" or payload.get("network") != NETWORK:
            raise X402Error("INVALID_PAYMENT", "scheme/network не поддерживаются")
        auth = (payload.get("payload") or {}).get("authorization") or {}
        signature = (payload.get("payload") or {}).get("signature") or ""
        for field in ("from", "to", "value", "validAfter", "validBefore", "nonce"):
            if field not in auth:
                raise X402Error("INVALID_PAYMENT", f"нет поля authorization.{field}")
        if not signature:
            raise X402Error("INVALID_PAYMENT", "нет payload.signature")
        return {"authorization": auth, "signature": signature}

    def verify_payment(self, payment_header: str) -> dict:
        """Проверка подписи и параметров БЕЗ сети (кроме чтения nonce/баланса при settle)."""
        self._connect()
        decoded = self._decode_header(payment_header)
        auth = decoded["authorization"]
        signature = decoded["signature"]

        from eth_account import Account
        from eth_account.messages import encode_typed_data

        if auth["to"].lower() != (self.pay_to or "").lower():
            raise X402Error("WRONG_PAYEE", "payTo не совпадает")
        value = int(auth["value"])
        if value < int(self.price_wei):
            raise X402Error("INSUFFICIENT", f"нужно ≥ {self.price_wei} wei, получено {value}")
        now = int(time.time())
        if now <= int(auth["validAfter"]):
            raise X402Error("NOT_YET_VALID", "authorization ещё не активна")
        if now >= int(auth["validBefore"]):
            raise X402Error("EXPIRED", "authorization просрочена")

        domain = {
            "name": ASSET_NAME,
            "version": ASSET_VERSION,
            "chainId": int(self._w3.eth.chain_id),
            "verifyingContract": self._w3.to_checksum_address(self.token_address),
        }
        types = {
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        }
        message = {
            "from": self._w3.to_checksum_address(auth["from"]),
            "to": self._w3.to_checksum_address(auth["to"]),
            "value": value,
            "validAfter": int(auth["validAfter"]),
            "validBefore": int(auth["validBefore"]),
            "nonce": auth["nonce"],
        }
        encoded = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
        signer = Account.recover_message(encoded, signature=signature)
        if signer.lower() != str(auth["from"]).lower():
            raise X402Error("BAD_SIGNATURE", "подпись не соответствует from")
        return {
            "from": message["from"],
            "to": message["to"],
            "value": value,
            "validAfter": message["validAfter"],
            "validBefore": message["validBefore"],
            "nonce": auth["nonce"],
            "signature": signature,
        }

    # ── сеттлмент (сервер платит газ) ────────────────────────────
    def _settle(self, payment: dict) -> dict:
        self._connect()
        if not self._private_key:
            raise X402Error("SIGNER_MISSING", "Ключ сеттлера не настроен")
        token = self._token
        from_addr = self._w3.to_checksum_address(payment["from"])
        if token.functions.authorizationState(from_addr, payment["nonce"]).call():
            raise X402Error("NONCE_USED", "Эта авторизация уже использована")
        balance = token.functions.balanceOf(from_addr).call()
        if int(balance) < int(payment["value"]):
            raise X402Error("INSUFFICIENT_BALANCE", "Недостаточно средств у плательщика")

        sig = bytes.fromhex(payment["signature"].removeprefix("0x"))
        r, s = sig[:32], sig[32:64]
        v = sig[64] if len(sig) == 65 else sig[64] - 27
        if v < 27:
            v += 27

        fn = token.functions.transferWithAuthorization(
            from_addr,
            self._w3.to_checksum_address(payment["to"]),
            int(payment["value"]),
            int(payment["validAfter"]),
            int(payment["validBefore"]),
            payment["nonce"],
            v, r, s,
        )
        settler = self._w3.eth.account.from_key(self._private_key).address
        tx = fn.build_transaction({
            "from": settler,
            "nonce": self._w3.eth.get_transaction_count(settler),
            "chainId": self._w3.eth.chain_id,
        })
        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if int(receipt.status) != 1:
            raise X402Error("SETTLE_FAILED", "Транзакция сеттлмента не прошла")
        return {
            "tx_hash": tx_hash.hex(),
            "block": int(receipt.blockNumber),
            "gas_used": int(receipt.gasUsed),
            "network": NETWORK,
            "payer": payment["from"],
            "amount_wei": str(payment["value"]),
        }

    async def verify_and_settle(self, payment_header: str) -> dict:
        def _flow() -> dict:
            payment = self.verify_payment(payment_header)
            return self._settle(payment)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_flow), 240.0)
        except X402Error:
            raise
        except Exception as e:  # noqa: BLE001
            raise X402Error("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e
