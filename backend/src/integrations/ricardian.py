"""Ricardian-соглашения (S6-03): чтение и запись в контракт RicardianAgreement.

Тестнет-only (Sepolia 11155111 / local anvil 31337): реальные сети запрещены.
Перед отправкой каждой транзакции — симуляция (`eth_call`): ошибка контракта
возвращается честно и НЕ отправляется. Ключ подписи — из окружения
(`KARTA_RICARDIAN_PRIVATE_KEY` или `WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY`).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from ..config.settings import get_settings

ALLOWED_CHAINS = {11155111, 31337}

RICARDIAN_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "nextAgreementId", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "createAgreement", "stateMutability": "nonpayable",
     "inputs": [
         {"name": "agreementHash_", "type": "bytes32"},
         {"name": "parties_", "type": "address[]"},
         {"name": "token_", "type": "address"},
         {"name": "milestoneDescriptions", "type": "string[]"},
         {"name": "milestoneAmounts", "type": "uint256[]"},
         {"name": "milestoneDeadlines", "type": "uint256[]"},
     ], "outputs": [{"name": "agreementId", "type": "uint256"}]},
    {"type": "function", "name": "signAgreement", "stateMutability": "nonpayable",
     "inputs": [{"name": "agreementId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "executeMilestone", "stateMutability": "nonpayable",
     "inputs": [{"name": "agreementId", "type": "uint256"},
                {"name": "milestoneIndex", "type": "uint256"},
                {"name": "payee", "type": "address"}], "outputs": []},
    {"type": "function", "name": "disputeMilestone", "stateMutability": "nonpayable",
     "inputs": [{"name": "agreementId", "type": "uint256"},
                {"name": "milestoneIndex", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "getAgreement", "stateMutability": "view",
     "inputs": [{"name": "agreementId", "type": "uint256"}],
     "outputs": [
         {"name": "agreementHash", "type": "bytes32"},
         {"name": "parties", "type": "address[]"},
         {"name": "token", "type": "address"},
         {"name": "totalAmount", "type": "uint256"},
         {"name": "milestoneCount", "type": "uint256"},
         {"name": "status", "type": "uint8"},
         {"name": "signCount", "type": "uint8"},
     ]},
    {"type": "function", "name": "getMilestone", "stateMutability": "view",
     "inputs": [{"name": "agreementId", "type": "uint256"},
                {"name": "milestoneIndex", "type": "uint256"}],
     "outputs": [
         {"name": "description", "type": "string"},
         {"name": "amount", "type": "uint256"},
         {"name": "deadline", "type": "uint256"},
         {"name": "completed", "type": "bool"},
         {"name": "disputed", "type": "bool"},
     ]},
    {"type": "function", "name": "isParty", "stateMutability": "view",
     "inputs": [{"name": "agreementId", "type": "uint256"},
                {"name": "account", "type": "address"}],
     "outputs": [{"type": "bool"}]},
]

STATUS_NAMES = ["draft", "signed", "active", "completed", "disputed"]


class RicardianError(Exception):
    """Ошибка Ricardian-сервиса (honest): code + сообщение."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _signer_key() -> str:
    settings = get_settings()
    key = (
        os.getenv("KARTA_RICARDIAN_PRIVATE_KEY", "").strip()
        or settings.karta_ricardian_private_key.strip()
        or os.getenv("WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY", "").strip()
        or settings.wallet_metamask_eth_erc20_private_key.strip()
    )
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class RicardianService:
    def __init__(self, rpc_url: Optional[str] = None, contract_address: Optional[str] = None,
                 private_key: Optional[str] = None):
        settings = get_settings()
        self.rpc_url = rpc_url if rpc_url is not None else settings.ricardian_rpc_url
        self.contract_address = (
            contract_address if contract_address is not None else settings.ricardian_contract_address
        )
        self._private_key = private_key if private_key is not None else _signer_key()
        self._w3 = None
        self._contract = None

    # ── подключение ──────────────────────────────────────────────
    def _connect(self):
        if self._contract is not None:
            return
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10.0}))
        if not self.contract_address:
            raise RicardianError("NOT_CONFIGURED", "Адрес контракта Ricardian не задан")
        if self._w3.eth.chain_id not in ALLOWED_CHAINS:
            raise RicardianError(
                "MAINNET_FORBIDDEN",
                f"Ricardian-операции разрешены только в тестнете (chain {self._w3.eth.chain_id})",
            )
        self._contract = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self.contract_address), abi=RICARDIAN_ABI
        )

    @property
    def signer_address(self) -> Optional[str]:
        if not self._private_key:
            return None
        from eth_account import Account

        return Account.from_key(self._private_key).address

    # ── чтение ───────────────────────────────────────────────────
    def _agreement_dict(self, agreement_id: int) -> dict:
        (hash_, parties, token, total, count, status, sign_count) = self._contract.functions \
            .getAgreement(agreement_id).call()
        milestones = []
        for i in range(count):
            desc, amount, deadline, completed, disputed = self._contract.functions \
                .getMilestone(agreement_id, i).call()
            milestones.append({
                "index": i, "description": desc, "amount_wei": str(amount),
                "deadline": int(deadline), "completed": bool(completed),
                "disputed": bool(disputed),
            })
        return {
            "id": agreement_id,
            "agreement_hash": "0x" + hash_.hex() if isinstance(hash_, bytes) else str(hash_),
            "parties": [p for p in parties],
            "token": token,
            "total_amount_wei": str(total),
            "status": STATUS_NAMES[status] if 0 <= status < len(STATUS_NAMES) else str(status),
            "sign_count": int(sign_count),
            "milestones": milestones,
        }

    async def list_agreements(self, limit: int = 20) -> list[dict]:
        def _read() -> list[dict]:
            self._connect()
            total = int(self._contract.functions.nextAgreementId().call())
            start = max(0, total - limit)
            return [self._agreement_dict(i) for i in range(total - 1, start - 1, -1)]

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except RicardianError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RicardianError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def get_agreement(self, agreement_id: int) -> dict:
        def _read() -> dict:
            self._connect()
            total = int(self._contract.functions.nextAgreementId().call())
            if agreement_id < 0 or agreement_id >= total:
                raise RicardianError("NOT_FOUND", f"Соглашение {agreement_id} не найдено")
            return self._agreement_dict(agreement_id)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except RicardianError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RicardianError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    # ── запись (тестнет, с симуляцией) ───────────────────────────
    def _send(self, fn_name: str, args: list) -> dict:
        self._connect()
        if not self._private_key:
            raise RicardianError(
                "SIGNER_MISSING",
                "Ключ подписанта не настроен (KARTA_RICARDIAN_PRIVATE_KEY)",
            )
        signer = self.signer_address
        fn = getattr(self._contract.functions, fn_name)(*args)
        tx = fn.build_transaction({
            "from": signer,
            "nonce": self._w3.eth.get_transaction_count(signer),
            "chainId": self._w3.eth.chain_id,
        })
        # Симуляция до отправки: revert → честная ошибка, tx не уходит
        try:
            fn.call({"from": signer})
        except Exception as e:  # noqa: BLE001
            raise RicardianError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return {
            "tx_hash": tx_hash.hex(),
            "status": int(receipt.status),
            "block": int(receipt.blockNumber),
            "gas_used": int(receipt.gasUsed),
        }

    async def _write_call(self, fn_name: str, args: list) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._send, fn_name, args), 180.0)
        except RicardianError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RicardianError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def create_agreement(self, parties: list[str], token: str,
                               milestones: list[dict], agreement_hash: Optional[str] = None) -> dict:
        import hashlib

        if not milestones:
            raise RicardianError("BAD_INPUT", "Нужен хотя бы один milestone")
        if agreement_hash:
            hash_bytes = bytes.fromhex(agreement_hash.removeprefix("0x"))
            if len(hash_bytes) != 32:
                raise RicardianError("BAD_INPUT", "agreement_hash должен быть 32 байта")
        else:
            payload = "|".join(
                [str(m["description"]) + str(m["amount_wei"]) for m in milestones]
            ).encode()
            hash_bytes = hashlib.sha256(payload).digest()

        def _write() -> dict:
            self._connect()
            before = int(self._contract.functions.nextAgreementId().call())
            result = self._send("createAgreement", [
                hash_bytes,
                [self._w3.to_checksum_address(p) for p in parties],
                self._w3.to_checksum_address(token),
                [str(m["description"]) for m in milestones],
                [int(m["amount_wei"]) for m in milestones],
                [int(m["deadline"]) for m in milestones],
            ])
            result["agreement_id"] = before
            result["agreement_hash"] = "0x" + hash_bytes.hex()
            return result

        try:
            return await asyncio.wait_for(asyncio.to_thread(_write), 180.0)
        except RicardianError:
            raise
        except Exception as e:  # noqa: BLE001
            raise RicardianError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def sign(self, agreement_id: int) -> dict:
        return await self._write_call("signAgreement", [int(agreement_id)])

    async def execute_milestone(self, agreement_id: int, index: int, payee: str) -> dict:
        def _args():
            self._connect()
            return [int(agreement_id), int(index), self._w3.to_checksum_address(payee)]

        return await self._write_call("executeMilestone", _args())

    async def dispute_milestone(self, agreement_id: int, index: int) -> dict:
        return await self._write_call("disputeMilestone", [int(agreement_id), int(index)])
