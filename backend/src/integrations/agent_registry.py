"""ERC-8004-совместимый реестр агентов (S6-01): паспорт on-chain + репутация.

Тестнет-only (Sepolia 11155111 / anvil 31337). Перед отправкой — симуляция.
Регистрация: `registerAgent(name, metadataURI)`; имя уникально on-chain.
`verifyAgent`/`updateReputation` — только владелец on-chain (наш тестнет-кошелёк).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from ..config.settings import get_settings

ALLOWED_CHAINS = {11155111, 31337}

REGISTRY_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "nextAgentId", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "totalRegistered", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "registerAgent", "stateMutability": "nonpayable",
     "inputs": [{"name": "name_", "type": "string"},
                {"name": "metadataURI_", "type": "string"}],
     "outputs": [{"name": "agentId", "type": "uint256"}]},
    {"type": "function", "name": "verifyAgent", "stateMutability": "nonpayable",
     "inputs": [{"name": "agentId", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "updateReputation", "stateMutability": "nonpayable",
     "inputs": [{"name": "agentId", "type": "uint256"},
                {"name": "newScore", "type": "uint8"}], "outputs": []},
    {"type": "function", "name": "getAgent", "stateMutability": "view",
     "inputs": [{"name": "agentId", "type": "uint256"}],
     "outputs": [
         {"name": "name", "type": "string"},
         {"name": "metadataURI", "type": "string"},
         {"name": "owner", "type": "address"},
         {"name": "registeredAt", "type": "uint48"},
         {"name": "verified", "type": "bool"},
         {"name": "reputation", "type": "uint8"},
     ]},
    {"type": "function", "name": "resolveName", "stateMutability": "view",
     "inputs": [{"name": "name_", "type": "string"}],
     "outputs": [{"name": "agentId", "type": "uint256"}]},
    {"type": "function", "name": "getAgentsByOwner", "stateMutability": "view",
     "inputs": [{"name": "owner", "type": "address"}],
     "outputs": [{"type": "uint256[]"}]},
]


class AgentRegistryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _signer_key() -> str:
    settings = get_settings()
    key = (
        os.getenv("KARTA_REGISTRY_PRIVATE_KEY", "").strip()
        or os.getenv("KARTA_RICARDIAN_PRIVATE_KEY", "").strip()
        or settings.karta_ricardian_private_key.strip()
        or os.getenv("WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY", "").strip()
        or settings.wallet_metamask_eth_erc20_private_key.strip()
    )
    if key and not key.startswith("0x"):
        key = "0x" + key
    return key


class AgentRegistryService:
    def __init__(self, rpc_url: Optional[str] = None, contract_address: Optional[str] = None,
                 private_key: Optional[str] = None):
        settings = get_settings()
        self.rpc_url = rpc_url if rpc_url is not None else settings.registry_rpc_url
        self.contract_address = (
            contract_address if contract_address is not None else settings.registry_contract_address
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
            raise AgentRegistryError("NOT_CONFIGURED", "Адрес контракта реестра не задан")
        if self._w3.eth.chain_id not in ALLOWED_CHAINS:
            raise AgentRegistryError(
                "MAINNET_FORBIDDEN",
                f"Операции реестра разрешены только в тестнете (chain {self._w3.eth.chain_id})",
            )
        self._contract = self._w3.eth.contract(
            address=self._w3.to_checksum_address(self.contract_address), abi=REGISTRY_ABI
        )

    @property
    def signer_address(self) -> Optional[str]:
        if not self._private_key:
            return None
        from eth_account import Account

        return Account.from_key(self._private_key).address

    # ── чтение ───────────────────────────────────────────────────
    async def get_agent(self, agent_id: int) -> dict:
        def _read() -> dict:
            self._connect()
            name, uri, owner, registered_at, verified, reputation = self._contract.functions \
                .getAgent(agent_id).call()
            return {
                "agent_id": int(agent_id),
                "name": name,
                "metadata_uri": uri,
                "owner": owner,
                "registered_at": int(registered_at),
                "verified": bool(verified),
                "reputation": int(reputation),
            }

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except AgentRegistryError:
            raise
        except Exception as e:  # noqa: BLE001
            if "AgentNotFound" in str(e):
                raise AgentRegistryError("NOT_FOUND", "Агент не зарегистрирован") from e
            raise AgentRegistryError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def resolve_name(self, name: str) -> Optional[int]:
        def _read() -> Optional[int]:
            self._connect()
            agent_id = int(self._contract.functions.resolveName(name).call())
            if agent_id != 0:
                return agent_id
            # resolveName=0 неоднозначен (нет имени ИЛИ агент #0): сверяем имя записи #0
            try:
                record = self._contract.functions.getAgent(0).call()
                if record[0] == name:
                    return 0
            except Exception:  # noqa: BLE001
                pass
            return None

        try:
            return await asyncio.wait_for(asyncio.to_thread(_read), 30.0)
        except AgentRegistryError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AgentRegistryError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    # ── запись ───────────────────────────────────────────────────
    def _send(self, fn_name: str, args: list) -> dict:
        self._connect()
        if not self._private_key:
            raise AgentRegistryError(
                "SIGNER_MISSING", "Ключ подписанта не настроен (KARTA_REGISTRY_PRIVATE_KEY)"
            )
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
            raise AgentRegistryError("SIMULATION_REVERT", f"Симуляция отклонена: {e}") from e
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
        except AgentRegistryError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AgentRegistryError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def register(self, name: str, metadata_uri: str) -> dict:
        def _write() -> dict:
            self._connect()
            before = int(self._contract.functions.nextAgentId().call())
            result = self._send("registerAgent", [name, metadata_uri])
            result["agent_id"] = before
            result["name"] = name
            return result

        try:
            return await asyncio.wait_for(asyncio.to_thread(_write), 180.0)
        except AgentRegistryError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AgentRegistryError("RPC_UNAVAILABLE", f"RPC недоступен: {type(e).__name__}") from e

    async def verify(self, agent_id: int) -> dict:
        return await self._write_call("verifyAgent", [int(agent_id)])

    async def set_reputation(self, agent_id: int, score: int) -> dict:
        score = max(0, min(int(score), 100))
        return await self._write_call("updateReputation", [int(agent_id), score])
