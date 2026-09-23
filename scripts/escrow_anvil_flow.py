#!/usr/bin/env python3
"""Полный цикл Escrow-аренды на локальном anvil (S6-02, бесплатно).

Сценарии: (1) create→release (агент получил оплату); (2) create→dispute→resolve(арбитр: агенту);
(3) create→refund (возврат заказчику).
Запуск (из корня репозитория):
    backend/.venv/bin/python scripts/escrow_anvil_flow.py
"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from web3 import Web3  # noqa: E402

from src.integrations.escrow import ERC20_ABI, ESCROW_ABI  # noqa: E402

ANVIL_BIN = pathlib.Path.home() / ".foundry" / "bin" / "anvil"
RPC = "http://127.0.0.1:8548"
PAYER = ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
         "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
AGENT = ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
         "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")


def load_artifact(name: str) -> dict:
    base = ROOT / "smart-contracts" / "artifacts" / "contracts"
    matches = list(base.rglob(f"{name}.sol/{name}.json"))
    if not matches:
        raise SystemExit(f"нет артефакта {name} — сначала: cd smart-contracts && npx hardhat compile")
    return json.loads(matches[0].read_text())


def send(w3, fn, private_key: str):
    signer = w3.eth.account.from_key(private_key).address
    tx = fn.build_transaction({
        "from": signer,
        "nonce": w3.eth.get_transaction_count(signer),
        "chainId": w3.eth.chain_id,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
    assert receipt.status == 1, f"tx failed: {receipt}"
    return receipt


def main() -> None:
    anvil = subprocess.Popen(
        [str(ANVIL_BIN), "--port", "8548", "--silent"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
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

        escrow_art = load_artifact("Escrow")
        token_art = load_artifact("MockERC20")

        receipt = send(w3, w3.eth.contract(
            abi=escrow_art["abi"], bytecode=escrow_art["bytecode"]).constructor(PAYER[0]), PAYER[1])
        escrow = w3.eth.contract(address=receipt.contractAddress, abi=escrow_art["abi"])
        receipt = send(w3, w3.eth.contract(
            abi=token_art["abi"], bytecode=token_art["bytecode"]).constructor("Mock USDC", "mUSDC"), PAYER[1])
        token = w3.eth.contract(address=receipt.contractAddress, abi=token_art["abi"])
        print("Escrow:", escrow.address, "| mUSDC:", token.address)

        send(w3, token.functions.mint(PAYER[0], 10_000), PAYER[1])
        send(w3, token.functions.approve(escrow.address, 10_000), PAYER[1])

        def balance(addr):
            return token.functions.balanceOf(addr).call()

        def status(escrow_id):
            _, _, amount, _, released, refunded, disputed, _ = escrow.functions.getEscrow(escrow_id).call()
            return ("released" if released else "refunded" if refunded else
                    "disputed" if disputed else "locked"), amount

        # 1) create → release
        send(w3, escrow.functions.createEscrow(AGENT[0], token.address, 1000), PAYER[1])
        before = balance(AGENT[0])
        send(w3, escrow.functions.release(0), PAYER[1])
        print("1) release:", status(0), "| агенту +", balance(AGENT[0]) - before)
        assert status(0)[0] == "released" and balance(AGENT[0]) - before == 1000

        # 2) create → dispute (агент) → resolve (арбитр: агенту)
        send(w3, escrow.functions.createEscrow(AGENT[0], token.address, 2000), PAYER[1])
        send(w3, escrow.functions.dispute(1), AGENT[1])
        print("2) после dispute:", status(1))
        before = balance(AGENT[0])
        send(w3, escrow.functions.resolve(1, True), PAYER[1])
        print("2) resolve(агенту):", status(1), "| агенту +", balance(AGENT[0]) - before)
        assert status(1)[0] == "released" and balance(AGENT[0]) - before == 2000

        # 3) create → refund
        send(w3, escrow.functions.createEscrow(AGENT[0], token.address, 3000), PAYER[1])
        before = balance(PAYER[0])
        send(w3, escrow.functions.refund(2), PAYER[1])
        print("3) refund:", status(2), "| заказчику +", balance(PAYER[0]) - before)
        assert status(2)[0] == "refunded" and balance(PAYER[0]) - before == 3000

        assert escrow.functions.nextEscrowId().call() == 3
        print("ИТОГ: Escrow-цикл на anvil — УСПЕХ (release / dispute+resolve / refund)")
    finally:
        anvil.terminate()
        anvil.wait(timeout=10)


if __name__ == "__main__":
    main()
