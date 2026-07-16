"""
Execution Layer — signs and broadcasts transactions to EVM chains.

Handles wallet management, gas estimation, nonce management,
spending limits, and retry logic.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from web3 import Web3
from web3.middleware import geth_poa_middleware

logger = logging.getLogger("agent.execution")


class TxStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    DROPPED = "dropped"
    REVERTED = "reverted"


@dataclass
class TransactionResult:
    tx_hash: str
    status: TxStatus
    chain: str
    from_address: str
    to_address: str
    value: float
    gas_used: int
    gas_price_gwei: float
    block_number: Optional[int] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "tx_hash": self.tx_hash,
            "status": self.status.value,
            "chain": self.chain,
            "from": self.from_address,
            "to": self.to_address,
            "value": self.value,
            "gas_used": self.gas_used,
            "gas_price_gwei": self.gas_price_gwei,
            "block_number": self.block_number,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SpendingLimit:
    daily_limit: float = 5.0  # ETH
    per_tx_limit: float = 1.0  # ETH
    whitelist: set = field(default_factory=set)  # contract addresses
    blacklist: set = field(default_factory=set)  # addresses to never interact with
    current_daily_spend: float = 0.0
    last_reset: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class WalletManager:
    """Manages EVM wallets with session keys and spending limits."""

    ERC20_ABI = [
        {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
         "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals",
         "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
        {"constant": False, "inputs": [
            {"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}
        ], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
        {"constant": True, "inputs": [
            {"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}
        ], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    ]

    def __init__(self, private_key: str, chain: str = "ethereum"):
        self.private_key = private_key
        self.chain = chain
        self.address = self._derive_address()
        self._nonces: dict[str, int] = {}

    def _derive_address(self) -> str:
        from eth_account import Account
        account = Account.from_key(self.private_key)
        return account.address

    def get_nonce(self, w3: Web3) -> int:
        chain_id = str(w3.eth.chain_id)
        if chain_id not in self._nonces:
            self._nonces[chain_id] = w3.eth.get_transaction_count(self.address, "pending")
        nonce = self._nonces[chain_id]
        self._nonces[chain_id] = nonce + 1
        return nonce

    def get_token_balance(self, w3: Web3, token_address: str) -> float:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=self.ERC20_ABI,
        )
        decimals = contract.functions.decimals().call()
        balance = contract.functions.balanceOf(Web3.to_checksum_address(self.address)).call()
        return balance / (10 ** decimals)

    def get_allowance(self, w3: Web3, token_address: str, spender: str) -> float:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=self.ERC20_ABI,
        )
        decimals = contract.functions.decimals().call()
        allowance = contract.functions.allowance(
            Web3.to_checksum_address(self.address),
            Web3.to_checksum_address(spender),
        ).call()
        return allowance / (10 ** decimals)

    def sign_transaction(self, w3: Web3, tx: dict) -> str:
        signed = w3.eth.account.sign_transaction(tx, self.private_key)
        return signed.raw_transaction


class TransactionExecutor:
    """Executes transactions with safety checks and retry logic."""

    MAX_RETRIES = 3
    RETRY_DELAY = 5  # seconds
    GAS_MULTIPLIER = 1.2  # 20% buffer

    def __init__(self, wallet: WalletManager, w3: Web3, spending_limit: SpendingLimit = None):
        self.wallet = wallet
        self.w3 = w3
        self.spending_limit = spending_limit or SpendingLimit()
        self.tx_log: list[TransactionResult] = []

    def check_spending_limit(self, value_eth: float, to_address: str) -> tuple[bool, str]:
        if to_address.lower() in self.spending_limit.blacklist:
            return False, f"Address {to_address} is blacklisted"

        if (self.spending_limit.whitelist and
                to_address.lower() not in self.spending_limit.whitelist):
            return False, f"Address {to_address} not in whitelist"

        if value_eth > self.spending_limit.per_tx_limit:
            return False, f"Amount {value_eth} ETH exceeds per-tx limit {self.spending_limit.per_tx_limit} ETH"

        if value_eth > self.spending_limit.daily_limit - self.spending_limit.current_daily_spend:
            return False, f"Would exceed daily limit (spent: {self.spending_limit.current_daily_spend})"

        return True, "OK"

    def send_eth(self, to_address: str, amount_eth: float,
                 chain: str = "ethereum", gas_limit: int = 21000) -> TransactionResult:
        allowed, reason = self.check_spending_limit(amount_eth, to_address)
        if not allowed:
            return TransactionResult(
                tx_hash="",
                status=TxStatus.FAILED,
                chain=chain,
                from_address=self.wallet.address,
                to_address=to_address,
                value=amount_eth,
                gas_used=0,
                gas_price_gwei=0,
                error=f"Spending limit: {reason}",
            )

        value_wei = self.w3.to_wei(amount_eth, "ether")
        gas_price = int(self.w3.eth.gas_price * self.GAS_MULTIPLIER)
        nonce = self.wallet.get_nonce(self.w3)

        tx = {
            "from": Web3.to_checksum_address(self.wallet.address),
            "to": Web3.to_checksum_address(to_address),
            "value": value_wei,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": self.w3.eth.chain_id,
        }

        return self._execute_with_retry(tx, amount_eth, to_address, chain)

    def call_contract(self, contract_address: str, abi: list, function_name: str,
                      args: list = None, value_eth: float = 0,
                      chain: str = "ethereum") -> TransactionResult:
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=abi,
        )
        func = contract.functions[function_name](*(args or []))

        value_wei = self.w3.to_wei(value_eth, "ether") if value_eth > 0 else 0
        gas_price = int(self.w3.eth.gas_price * self.GAS_MULTIPLIER)
        nonce = self.wallet.get_nonce(self.w3)

        try:
            gas_estimate = func.estimate_gas({
                "from": Web3.to_checksum_address(self.wallet.address),
                "value": value_wei,
            })
        except Exception as e:
            return TransactionResult(
                tx_hash="",
                status=TxStatus.FAILED,
                chain=chain,
                from_address=self.wallet.address,
                to_address=contract_address,
                value=value_eth,
                gas_used=0,
                gas_price_gwei=float(Web3.from_wei(gas_price, "gwei")),
                error=f"Gas estimation failed: {e}",
            )

        tx = func.build_transaction({
            "from": Web3.to_checksum_address(self.wallet.address),
            "gas": int(gas_estimate * self.GAS_MULTIPLIER),
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": self.w3.eth.chain_id,
            "value": value_wei,
        })

        return self._execute_with_retry(tx, value_eth, contract_address, chain)

    def approve_token(self, token_address: str, spender: str,
                      amount: float = None, chain: str = "ethereum") -> TransactionResult:
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=self.ERC20_ABI,
        )

        decimals = contract.functions.decimals().call()
        if amount is None:
            approve_amount = 2**256 - 1  # max approval
        else:
            approve_amount = int(amount * (10 ** decimals))

        gas_price = int(self.w3.eth.gas_price * self.GAS_MULTIPLIER)
        nonce = self.wallet.get_nonce(self.w3)

        func = contract.functions.approve(
            Web3.to_checksum_address(spender),
            approve_amount,
        )

        try:
            gas_estimate = func.estimate_gas({
                "from": Web3.to_checksum_address(self.wallet.address),
            })
        except Exception as e:
            return TransactionResult(
                tx_hash="", status=TxStatus.FAILED, chain=chain,
                from_address=self.wallet.address, to_address=spender,
                value=0, gas_used=0, gas_price_gwei=0,
                error=f"Approve gas estimation failed: {e}",
            )

        tx = func.build_transaction({
            "from": Web3.to_checksum_address(self.wallet.address),
            "gas": int(gas_estimate * self.GAS_MULTIPLIER),
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": self.w3.eth.chain_id,
        })

        return self._execute_with_retry(tx, 0, spender, chain)

    def _execute_with_retry(self, tx: dict, value_eth: float,
                            to_address: str, chain: str) -> TransactionResult:
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                raw_tx = self.wallet.sign_transaction(self.w3, tx)
                tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
                tx_hash_hex = tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash

                logger.info(f"TX submitted: {tx_hash_hex} (attempt {attempt + 1})")

                receipt = self._wait_for_receipt(tx_hash_hex, chain)

                result = TransactionResult(
                    tx_hash=tx_hash_hex,
                    status=TxStatus.CONFIRMED if receipt["status"] == 1 else TxStatus.REVERTED,
                    chain=chain,
                    from_address=self.wallet.address,
                    to_address=to_address,
                    value=value_eth,
                    gas_used=receipt["gas_used"],
                    gas_price_gwei=float(Web3.from_wei(tx.get("gasPrice", 0), "gwei")),
                    block_number=receipt["block_number"],
                    error=None if receipt["status"] == 1 else "Transaction reverted",
                )

                self.tx_log.append(result)

                if result.status == TxStatus.CONFIRMED:
                    self.spending_limit.current_daily_spend += value_eth
                    logger.info(f"TX confirmed: {tx_hash_hex} in block {receipt['block_number']}")
                else:
                    logger.warning(f"TX reverted: {tx_hash_hex}")

                return result

            except Exception as e:
                last_error = str(e)
                logger.warning(f"TX attempt {attempt + 1} failed: {e}")
                tx["nonce"] = self.wallet.get_nonce(self.w3)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)

        return TransactionResult(
            tx_hash="",
            status=TxStatus.FAILED,
            chain=chain,
            from_address=self.wallet.address,
            to_address=to_address,
            value=value_eth,
            gas_used=0,
            gas_price_gwei=0,
            error=f"All {self.MAX_RETRIES} attempts failed: {last_error}",
        )

    def _wait_for_receipt(self, tx_hash: str, chain: str,
                          timeout: int = 120, poll_interval: int = 2) -> dict:
        start = time.time()
        while time.time() - start < timeout:
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    return {
                        "status": receipt["status"],
                        "gas_used": receipt["gasUsed"],
                        "block_number": receipt["blockNumber"],
                    }
            except Exception:
                pass
            time.sleep(poll_interval)

        raise TimeoutError(f"TX {tx_hash} not confirmed within {timeout}s")

    def simulate_transaction(self, tx: dict) -> dict:
        try:
            result = self.w3.eth.call(tx)
            return {"success": True, "result": result.hex()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_daily_spend(self) -> float:
        return self.spending_limit.current_daily_spend

    def reset_daily_spend(self):
        self.spending_limit.current_daily_spend = 0.0
        self.spending_limit.last_reset = datetime.now(timezone.utc)
