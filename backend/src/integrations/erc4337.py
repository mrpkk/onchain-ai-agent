"""ERC-4337-сервис (S5-06): smart account + session keys (TTL/лимит/цель) + paymaster + recovery.

Локальный контур: наш KartaEntryPoint (bundler/paymaster-сервисы платные — решение
владельца), тестнет-only, симуляция до отправки. «Bundler» — наш кошелёк, вызывающий
handleOps; session key подписывает userOp (owner — тоже может).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from ..config.settings import get_settings

ALLOWED_CHAINS = {11155111, 31337}

ENTRYPOINT_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "handleOps", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "ops", "type": "tuple[]", "components": [
             {"name": "sender", "type": "address"},
             {"name": "nonce", "type": "uint256"},
             {"name": "target", "type": "address"},
             {"name": "value", "type": "uint256"},
             {"name": "data", "type": "bytes"},
             {"name": "paymaster", "type": "address"},
             {"name": "signature", "type": "bytes"},
         ]},
         {"name": "beneficiary", "type": "address"},
     ], "outputs": []},
    {"type": "function", "name": "getUserOpHash", "stateMutability": "view",
     "inputs": [{"name": "op", "type": "tuple", "components": [
         {"name": "sender", "type": "address"},
         {"name": "nonce", "type": "uint256"},
         {"name": "target", "type": "address"},
         {"name": "value", "type": "uint256"},
         {"name": "data", "type": "bytes"},
         {"name": "paymaster", "type": "address"},
         {"name": "signature", "type": "bytes"},
     ]}], "outputs": [{"type": "bytes32"}]},
]

ACCOUNT_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "owner", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "address"}]},
    {"type": "function", "name": "entryPoint", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "address"}]},
    {"type": "function", "name": "getNonce", "stateMutability": "view", "inputs": [],
     "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "addSessionKey", "stateMutability": "nonpayable",
     "inputs": [{"name": "key", "type": "address"},
                {"name": "validUntil", "type": "uint48"},
                {"name": "spendLimitWei", "type": "uint96"},
                {"name": "allowedTarget", "type": "address"}], "outputs": []},
    {"type": "function", "name": "revokeSessionKey", "stateMutability": "nonpayable",
     "inputs": [{"name": "key", "type": "address"}], "outputs": []},
    {"type": "function", "name": "addGuardian", "stateMutability": "nonpayable",
     "inputs": [{"name": "guardian", "type": "address"}], "outputs": []},
    {"type": "function", "name": "approveRecovery", "stateMutability": "nonpayable",
     "inputs": [{"name": "newOwner_", "type": "address"}], "outputs": []},
    {"type": "function", "name": "finalizeRecovery", "stateMutability": "nonpayable",
     "inputs": [], "outputs": []},
    {"type": "function", "name": "guardians", "stateMutability": "view",
     "inputs": [{"name": "", "type": "uint256"}], "outputs": [{"type": "address"}]},
]

ACCOUNT_DEPLOY_ABI: list[dict[str, Any]] = [
    {"type": "constructor", "inputs": [
        {"name": "owner_", "type": "address"}, {"name": "entryPoint_", "type": "address"}],
     "stateMutability": "nonpayable"},
]


class AAError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _key(name: str, fallback_env: str = "") -> str:
    settings = get_settings()
    key = os.getenv(name, "").strip() or settings.wallet_metamask_eth_erc20_private_key.strip()
    if not key and fallback_env:
        key = os.getenv(fallback_env, "").strip()
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class ERC4337Service:
    def __init__(self, rpc_url: Optional[str] = None, entrypoint: Optional[str] = None,
                 account: Optional[str] = None, owner_key: Optional[str] = None,
                 session_key: Optional[str] = None):
        settings = get_settings()
        self.rpc_url = rpc_url or settings.aa_rpc_url
        self.entrypoint = entrypoint if entrypoint is not None else settings.aa_entrypoint_address
        self.account = account if account is not None else settings.aa_account_address
        self._owner_key = owner_key if owner_key is not None else _key("KARTA_AA_OWNER_KEY")
        self._session_key = (
            session_key if session_key is not None
            else (os.getenv("KARTA_AA_SESSION_KEY", "").strip()
                  or settings.karta_aa_session_key.strip())
        )
        if self._session_key and not self._session_key.startswith("0x"):
            self._session_key = "0x" + self._session_key
        self._w3 = None
        self._ep = None
        self._account = None

    def _connect(self):
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10.0}))
        if self._w3.eth.chain_id not in ALLOWED_CHAINS:
            raise AAError("MAINNET_FORBIDDEN", "ERC-4337-контур разрешён только в тестнете")
        if self.entrypoint and self._ep is None:
            self._ep = self._w3.eth.contract(
                address=self._w3.to_checksum_address(self.entrypoint), abi=ENTRYPOINT_ABI)
        if self.account and self._account is None:
            self._account = self._w3.eth.contract(
                address=self._w3.to_checksum_address(self.account), abi=ACCOUNT_ABI)

    @property
    def owner_address(self) -> Optional[str]:
        if not self._owner_key:
            return None
        from eth_account import Account

        return Account.from_key(self._owner_key).address

    @property
    def session_key_address(self) -> Optional[str]:
        if not self._session_key:
            return None
        from eth_account import Account

        return Account.from_key(self._session_key).address

    # ── отправка (owner-транзакции) ──────────────────────────────
    def _send(self, fn) -> dict:
        self._connect()
        if not self._owner_key:
            raise AAError("SIGNER_MISSING", "Ключ owner не настроен")
        signer = self.owner_address
        tx = fn.build_transaction({
            "from": signer, "nonce": self._w3.eth.get_transaction_count(signer),
            "chainId": self._w3.eth.chain_id,
        })
        try:
            fn.call({"from": signer})
        except Exception as e:  # noqa: BLE001
            raise AAError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._owner_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        return {"tx_hash": tx_hash.hex(), "status": int(receipt.status),
                "block": int(receipt.blockNumber), "gas_used": int(receipt.gasUsed),
                "chain_id": int(self._w3.eth.chain_id)}

    async def _write(self, fn) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._send, fn), 240.0)
        except AAError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AAError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    # ── чтение ───────────────────────────────────────────────────
    async def info(self) -> dict:
        def _read() -> dict:
            self._connect()
            data: dict[str, Any] = {
                "entrypoint": self.entrypoint,
                "account": self.account,
                "owner": self.owner_address,
                "session_key": self.session_key_address,
                "session_key_configured": bool(self._session_key),
                "chain": "sepolia",
            }
            if self._account is not None:
                data["account_owner"] = self._account.functions.owner().call()
                data["nonce"] = int(self._account.functions.getNonce().call())
                guardians = []
                for i in range(10):
                    try:
                        guardians.append(self._account.functions.guardians(i).call())
                    except Exception:  # noqa: BLE001
                        break
                data["guardians"] = guardians
            return data

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 60.0)
        except AAError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AAError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    # ── session keys / guardians ─────────────────────────────────
    async def add_session_key(self, key_address: str, valid_until: int,
                              spend_limit_wei: int, allowed_target: str = "") -> dict:
        self._connect()
        if self._account is None:
            raise AAError("NOT_CONFIGURED", "Адрес smart account не задан")
        target = allowed_target or "0x0000000000000000000000000000000000000000"
        return await self._write(self._account.functions.addSessionKey(
            self._w3.to_checksum_address(key_address), int(valid_until),
            int(spend_limit_wei), self._w3.to_checksum_address(target),
        ))

    async def revoke_session_key(self, key_address: str) -> dict:
        self._connect()
        if self._account is None:
            raise AAError("NOT_CONFIGURED", "Адрес smart account не задан")
        return await self._write(self._account.functions.revokeSessionKey(
            self._w3.to_checksum_address(key_address)))

    async def add_guardian(self, guardian: str) -> dict:
        self._connect()
        if self._account is None:
            raise AAError("NOT_CONFIGURED", "Адрес smart account не задан")
        return await self._write(self._account.functions.addGuardian(
            self._w3.to_checksum_address(guardian)))

    # ── userOp: build → sign → handleOps (локальный bundler) ─────
    def _build_and_execute_sync(self, target: str, value: int, data: str,
                                use_session_key: bool) -> dict:
        self._connect()
        if self._ep is None or self._account is None:
            raise AAError("NOT_CONFIGURED", "EntryPoint/account не настроены")
        signer_key = self._session_key if use_session_key else self._owner_key
        if not signer_key:
            raise AAError("SIGNER_MISSING",
                          "Session key не настроен (KARTA_AA_SESSION_KEY)" if use_session_key
                          else "Owner-ключ не настроен")
        sender = self.account
        nonce = int(self._account.functions.getNonce().call())
        op = {
            "sender": self._w3.to_checksum_address(sender),
            "nonce": nonce,
            "target": self._w3.to_checksum_address(target),
            "value": int(value),
            "data": data or "0x",
            "paymaster": "0x0000000000000000000000000000000000000000",
            "signature": b"",
        }
        op_hash = self._ep.functions.getUserOpHash(op).call()
        from eth_account import Account

        # Контракт делает ecrecover(opHash) напрямую → подпись по «сырому» хэшу (без EIP-191)
        signer = getattr(Account, "unsafe_sign_hash", None) or getattr(Account, "signHash")
        signed = signer(op_hash, private_key=signer_key)
        op["signature"] = signed.signature

        bundler = self.owner_address
        handle_fn = self._ep.functions.handleOps([op], bundler)
        try:
            # Симуляция ДО сборки: estimateGas внутри build_transaction тоже ревертит
            handle_fn.call({"from": bundler})
            tx = handle_fn.build_transaction({
                "from": bundler, "nonce": self._w3.eth.get_transaction_count(bundler),
                "chainId": self._w3.eth.chain_id,
            })
        except Exception as e:  # noqa: BLE001
            raise AAError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
        signed_tx = self._w3.eth.account.sign_transaction(tx, private_key=self._owner_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        return {
            "tx_hash": tx_hash.hex(),
            "status": int(receipt.status),
            "block": int(receipt.blockNumber),
            "gas_used": int(receipt.gasUsed),
            "chain_id": int(self._w3.eth.chain_id),
            "sender": sender,
            "nonce": nonce,
            "signer": self.session_key_address if use_session_key else self.owner_address,
            "via_session_key": use_session_key,
        }

    async def execute_user_op(self, target: str, value: int = 0, data: str = "0x",
                              use_session_key: bool = False) -> dict:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._build_and_execute_sync, target, value, data,
                                  use_session_key),
                300.0,
            )
        except AAError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AAError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

