#!/usr/bin/env python3
"""Полный swap-цикл на локальном anvil (S5-01, бесплатно, без агрегаторов).

Сценарий: deploy (2 токена + MockDEX) → ликвидность → котировка → swap с
amountOutMin → проверка балансов/резервов → отказ при завышенном amountOutMin.
Запуск (из корня репозитория):
    backend/.venv/bin/python scripts/swap_anvil_flow.py
"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from web3 import Web3  # noqa: E402

ANVIL_BIN = pathlib.Path.home() / ".foundry" / "bin" / "anvil"
RPC = "http://127.0.0.1:8549"
OWNER = ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
         "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")


def load_artifact(name: str) -> dict:
    base = ROOT / "smart-contracts" / "artifacts" / "contracts"
    matches = list(base.rglob(f"{name}.sol/{name}.json"))
    if not matches:
        raise SystemExit(f"нет артефакта {name} — сначала: cd smart-contracts && npx hardhat compile")
    return json.loads(matches[0].read_text())


def send(w3, fn, key: str):
    signer = w3.eth.account.from_key(key).address
    tx = fn.build_transaction({
        "from": signer, "nonce": w3.eth.get_transaction_count(signer), "chainId": w3.eth.chain_id,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=key)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
    assert receipt.status == 1, f"tx failed: {receipt}"
    return receipt


def main() -> None:
    anvil = subprocess.Popen([str(ANVIL_BIN), "--port", "8549", "--silent"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 10.0}))
        for _ in range(30):
            try:
                if w3.is_connected():
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        assert w3.is_connected(), "anvil не поднялся"

        token_art = load_artifact("MockERC20EIP3009")
        dex_art = load_artifact("MockDEX")

        token_a = w3.eth.contract(abi=token_art["abi"], bytecode=token_art["bytecode"])
        receipt = send(w3, token_a.constructor("Mock USDC", "mUSDC"), OWNER[1])
        token_a = w3.eth.contract(address=receipt.contractAddress, abi=token_art["abi"])
        token_b = w3.eth.contract(abi=token_art["abi"], bytecode=token_art["bytecode"])
        receipt = send(w3, token_b.constructor("x402 Demo USD", "xUSDC"), OWNER[1])
        token_b = w3.eth.contract(address=receipt.contractAddress, abi=token_art["abi"])

        dex = w3.eth.contract(abi=dex_art["abi"], bytecode=dex_art["bytecode"])
        receipt = send(w3, dex.constructor(token_a.address, token_b.address), OWNER[1])
        dex = w3.eth.contract(address=receipt.contractAddress, abi=dex_art["abi"])
        print("mUSDC:", token_a.address, "| xUSDC:", token_b.address, "| MockDEX:", dex.address)

        send(w3, token_a.functions.mint(OWNER[0], 10_000 * 10**18), OWNER[1])
        send(w3, token_b.functions.mint(OWNER[0], 10_000 * 10**18), OWNER[1])
        send(w3, token_a.functions.approve(dex.address, 2**256 - 1), OWNER[1])
        send(w3, token_b.functions.approve(dex.address, 2**256 - 1), OWNER[1])
        send(w3, dex.functions.addLiquidity(5_000 * 10**18, 5_000 * 10**18), OWNER[1])
        print("ликвидность: 5000/5000")

        amount_in = 100 * 10**18
        amounts = dex.functions.getAmountsOut(amount_in, [token_a.address, token_b.address]).call()
        quote_out = amounts[1]
        print(f"котировка: {amount_in / 1e18} mUSDC → {quote_out / 1e18:.6f} xUSDC")

        before_b = token_b.functions.balanceOf(OWNER[0]).call()
        min_out = quote_out * 9950 // 10000  # slippage 0.5%
        send(w3, dex.functions.swapExactTokensForTokens(
            amount_in, min_out, [token_a.address, token_b.address], OWNER[0], 2**64), OWNER[1])
        got = token_b.functions.balanceOf(OWNER[0]).call() - before_b
        print(f"swap выполнен: получено {got / 1e18:.6f} xUSDC (min {min_out / 1e18:.6f})")
        assert got == quote_out

        # slippage-guard: завышенный amountOutMin → revert
        try:
            dex.functions.swapExactTokensForTokens(
                amount_in, quote_out * 105 // 100,
                [token_a.address, token_b.address], OWNER[0], 2**64).call({"from": OWNER[0]})
            raise AssertionError("ожидали revert по slippage")
        except Exception as e:  # noqa: BLE001
            selector = Web3.keccak(text="InsufficientOutput(uint256,uint256)")[:4].hex()
            assert selector in str(e).lower(), str(e)
            print("slippage-guard: завышенный amountOutMin → revert (InsufficientOutput) ✔")

        # обратный swap
        amounts = dex.functions.getAmountsOut(got, [token_b.address, token_a.address]).call()
        send(w3, dex.functions.swapExactTokensForTokens(
            got, amounts[1] * 9950 // 10000, [token_b.address, token_a.address], OWNER[0], 2**64), OWNER[1])
        print(f"обратный swap: {got / 1e18:.6f} xUSDC → {amounts[1] / 1e18:.6f} mUSDC ✔")
        print("ИТОГ: swap-цикл на anvil — УСПЕХ (котировка/swap/slippage-guard/reverse)")
    finally:
        anvil.terminate()
        anvil.wait(timeout=10)


if __name__ == "__main__":
    main()
