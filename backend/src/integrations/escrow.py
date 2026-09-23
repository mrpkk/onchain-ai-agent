"""Escrow-аренда агентов (S6-02): оплата в эскроу → release/refund/dispute/resolve.

Тестнет-only (Sepolia 11155111 / anvil 31337). Симуляция до отправки.
createEscrow тянет токены через transferFrom → сервис сам делает approve при
недостаточном allowance (две транзакции: approve → create).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from ..config.settings import get_settings

ALLOWED_CHAINS = {11155111, 31337}

ESCROW_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "nextEscrowId", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "owner", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "createEscrow", "stateMutability": "nonpayable",
     "inputs": [{"name": "payee_", "type": "address"},
                {"name": "token_", "type": "address"},
                {"name": "amount_", "type": "uint256"}],
     "outputs": [{"name": "escrowId", "type": "uint256"}]},
    {"type": "function", "name": "release", "stateMutability": "nonpayable",
     "inputs": [{"name": "escrowId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "refund", "stateMutability": "nonpayable",
     "inputs": [{"name": "escrowId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "dispute", "stateMutability": "nonpayable",
     "inputs": [{"name": "escrowId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "resolve", "stateMutability": "nonpayable",
     "inputs": [{"name": "escrowId", "type": "uint256"},
                {"name": "releaseToPayee", "type": "bool"}], "outputs": []},
    {"type": "function", "name": "getEscrow", "stateMutability": "view",
     "inputs": [{"name": "escrowId", "type": "uint256"}],
     "outputs": [
         {"name": "payer", "type": "address"},
         {"name": "payee", "type": "address"},
         {"name": "amount", "type": "uint256"},
         {"name": "token", "type": "address"},
         {"name": "released", "type": "bool"},
         {"name": "refunded", "type": "bool"},
         {"name": "disputed", "type": "bool"},
         {"name": "arbiter", "type": "address"},
     ]},
    {"type": "function", "name": "isFinalized", "stateMutability": "view",
     "inputs": [{"name": "escrowId", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
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


class EscrowError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _signer_key() -> str:
    settings = get_settings()
    key = (
        os.getenv("KARTA_ESCROW_PRIVATE_KEY", "").strip()
        or os.getenv("KARTA_REGISTRY_PRIVATE_KEY", "").strip()
        or os.getenv("KARTA_RICARDIAN_PRIVATE_KEY", "").strip()
        or settings.karta_ricardian_private_key.strip()
        or os.getenv("WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY", "").strip()
        or settings.wallet_metamask_eth_erc20_private_key.strip()
    )
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class EscrowService:
    def __init__(self, rpc_url: Optional[str] = None, contract_address: Optional[str] = None,
                 token_address: Optional[str] = None, private_key: Optional[str] = None):
        settings = get_settings()
        self.rpc_url = rpc_url if rpc_url is not None else settings.escrow_rpc_url
        self.contract_address = (
            contract_address if contract_address is not None else settings.escrow_contract_address
        )
        self.token_address = (
            token_address if token_address is not None else settings.escrow_token_address
        )
        self._private_key = private_key if private_key is not None else _signer_key()
        self._w3 = None
        self._contract = None

    def _connect(self):
        if self._contract is not None:
            return
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10.0}))
        if not self.contract_address:
            raise EscrowError("NOT_CONFIGURED", "Адрес контракта Escrow не задан")
        if self._w3.eth.chain_id not in ALLOWED_CHAINS:
            raise EscrowError(
                "MAINNET_FORBIDDEN",
                f"Escrow-операции разрешены только в тестнете (chain {self._w3.eth.chain_id})",
            )
        self._contract = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self.contract_address), abi=ESCROW_ABI
        )

    @property
    def signer_address(self) -> Optional[str]:
        if not self._private_key:
            return None
        from eth_account import Account

        return Account.from_key(self._private_key).address

    # ── чтение ───────────────────────────────────────────────────
    def _escrow_dict(self, escrow_id: int) -> dict:
        payer, payee, amount, token, released, refunded, disputed, arbiter = self._contract \
            .functions.getEscrow(escrow_id).call()
        if released:
            status = "released"
        elif refunded:
            status = "refunded"
        elif disputed:
            status = "disputed"
        else:
            status = "locked"
        return {
            "id": escrow_id,
            "payer": payer,
            "payee": payee,
            "amount_wei": str(amount),
            "token": token,
            "released": bool(released),
            "refunded": bool(refunded),
            "disputed": bool(disputed),
            "arbiter": arbiter,
            "status": status,
        }

    async def list_recent(self, limit: int = 20) -> list[dict]:
        def _read() -> list[dict]:
            self._connect()
            total = int(self._contract.functions.nextEscrowId().call())
            start = max(0, total - limit)
            return [self._escrow_dict(i) for i in range(total - 1, start - 1, -1)]

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except EscrowError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EscrowError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def get_escrow(self, escrow_id: int) -> dict:
        def _read() -> dict:
            self._connect()
            total = int(self._contract.functions.nextEscrowId().call())
            if escrow_id < 0 or escrow_id >= total:
                raise EscrowError("NOT_FOUND", f"Эскроу {escrow_id} не найден")
            return self._escrow_dict(escrow_id)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except EscrowError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EscrowError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def token_balance(self) -> Optional[float]:
        def _read() -> Optional[float]:
            self._connect()
            if not self.signer_address or not self.token_address:
                return None
            from web3 import Web3

            token = self._w3.eth.contract(
                address=Web3.to_checksum_address(self.token_address), abi=ERC20_ABI
            )
            return float(token.functions.balanceOf(self.signer_address).call()) / 1e18

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except Exception:  # noqa: BLE001 — баланс не критичен
            return None

    # ── запись ───────────────────────────────────────────────────
    def _send(self, fn_name: str, args: list) -> dict:
        self._connect()
        if not self._private_key:
            raise EscrowError("SIGNER_MISSING", "Ключ подписанта не настроен (KARTA_ESCROW_PRIVATE_KEY)")
        signer = self.signer_address
        fn = getattr(self._contract.functions, fn_name)(*args)
        tx = fn.build_transaction({
            "from": signer,
            "nonce": self._w3.eth.get_transaction_count(signer),
            "chainId": self._w3.eth.chain_id,
        })
        try:
            fn.call({"from": signer})
        except Exception as e:  # noqa: BLE001
            raise EscrowError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
        signed = self._w3.eth.account.sign_transaction(tx, private_key=self._private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return {
            "tx_hash": tx_hash.hex(),
            "status": int(receipt.status),
            "block": int(receipt.blockNumber),
            "gas_used": int(receipt.gasUsed),
            "chain_id": int(self._w3.eth.chain_id),
        }

    async def _write_call(self, fn_name: str, args: list) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._send, fn_name, args), 180.0)
        except EscrowError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EscrowError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def create_rental(self, payee: str, amount_wei: int,
                            token_address: Optional[str] = None) -> dict:
        """Аренда: approve (если нужно) → createEscrow. Возвращает tx-и и escrow_id."""
        token_addr = token_address or self.token_address

        def _write() -> dict:
            self._connect()
            from web3 import Web3

            if not self._private_key:
                raise EscrowError("SIGNER_MISSING", "Ключ подписанта не настроен")
            signer = self.signer_address
            token = self._w3.eth.contract(
                address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI
            )
            result: dict = {}
            allowance = int(token.functions.allowance(
                signer, self._w3.to_checksum_address(self.contract_address)).call())
            if allowance < int(amount_wei):
                # approve через тот же симуляционный контур (вручную: не escrow-функция)
                approve_fn = token.functions.approve(
                    self._w3.to_checksum_address(self.contract_address), int(amount_wei))
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

            before = int(self._contract.functions.nextEscrowId().call())
            create_result = self._send("createEscrow", [
                self._w3.to_checksum_address(payee),
                self._w3.to_checksum_address(token_addr),
                int(amount_wei),
            ])
            result.update(create_result)
            result["escrow_id"] = before
            result["payee"] = payee
            result["amount_wei"] = str(amount_wei)
            return result

        try:
            return await asyncio.wait_for(asyncio.to_thread(_write), 240.0)
        except EscrowError:
            raise
        except Exception as e:  # noqa: BLE001
            raise EscrowError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def release(self, escrow_id: int) -> dict:
        return await self._write_call("release", [int(escrow_id)])

    async def refund(self, escrow_id: int) -> dict:
        return await self._write_call("refund", [int(escrow_id)])

    async def dispute(self, escrow_id: int) -> dict:
        return await self._write_call("dispute", [int(escrow_id)])

    async def resolve(self, escrow_id: int, release_to_payee: bool) -> dict:
        return await self._write_call("resolve", [int(escrow_id), bool(release_to_payee)])
