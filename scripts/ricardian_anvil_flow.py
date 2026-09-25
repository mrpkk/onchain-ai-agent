#!/usr/bin/env python3
"""Полный 2-of-3 цикл Ricardian на локальном anvil (S6-03, бесплатно, без тестнета).

Сценарий: A создаёт (auto-подпись) → B и C подписывают → Active → эскроу пополнен →
время сдвинуто за дедлайн → веха исполнена → выплата получателю → статус Completed.

Запуск (из корня репозитория; anvil ставится Foundry):
    backend/.venv/bin/python scripts/ricardian_anvil_flow.py
Требует: ~/.foundry/bin/anvil, собранные артефакты (npx hardhat compile).
"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from web3 import Web3  # noqa: E402

from src.integrations.ricardian import RICARDIAN_ABI, STATUS_NAMES  # noqa: E402

ANVIL_BIN = pathlib.Path.home() / ".foundry" / "bin" / "anvil"
RPC = "http://127.0.0.1:8546"

# anvil default accounts (публичные тестовые ключи самого anvil)
A = ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
     "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
B = ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
     "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")
C = ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
     "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a")


def load_artifact(name: str) -> dict:
    base = ROOT / "smart-contracts" / "artifacts" / "contracts"
    matches = list(base.rglob(f"{name}.sol/{name}.json"))
    if not matches:
        raise SystemExit(f"нет артефакта {name} — сначала: cd smart-contracts && npx hardhat compile")
    return json.loads(matches[0].read_text())


def send(w3, fn, private_key: str, **overrides):
    signer = w3.eth.account.from_key(private_key).address
    tx = fn.build_transaction({
        "from": signer,
        "nonce": w3.eth.get_transaction_count(signer),
        "chainId": w3.eth.chain_id,
        **overrides,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
    assert receipt.status == 1, f"tx failed: {receipt}"
    return receipt


def main() -> None:
    anvil = subprocess.Popen(
        [str(ANVIL_BIN), "--port", "8546", "--silent"],
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
        print("anvil:", w3.eth.chain_id)

        ricardian_art = load_artifact("RicardianAgreement")
        token_art = load_artifact("MockERC20")

        ricardian = w3.eth.contract(
            abi=ricardian_art["abi"], bytecode=ricardian_art["bytecode"])
        receipt = send(w3, ricardian.constructor(), A[1])
        ricardian_addr = receipt.contractAddress
        ricardian = w3.eth.contract(address=ricardian_addr, abi=ricardian_art["abi"])
        print("RicardianAgreement:", ricardian_addr)

        token = w3.eth.contract(abi=token_art["abi"], bytecode=token_art["bytecode"])
        receipt = send(w3, token.constructor("Mock USDC", "mUSDC"), A[1])
        token_addr = receipt.contractAddress
        token = w3.eth.contract(address=token_addr, abi=token_art["abi"])
        print("MockERC20:", token_addr)

        # эскроу-фонд: 1000 mUSDC в контракт
        send(w3, token.functions.mint(A[0], 1000), A[1])
        send(w3, token.functions.transfer(ricardian_addr, 1000), A[1])

        now = int(time.time())
        create = ricardian.functions.createAgreement(
            b"\x42" * 32, [B[0], C[0]], token_addr,
            ["Design"], [1000], [now + 3600],
        )
        receipt = send(w3, create, A[1])
        agreement_id = 0
        print(f"createAgreement: id={agreement_id} tx={receipt.transactionHash.hex()[:14]}…")

        def status():
            (_, parties, _, total, _, st, sign_count) = ricardian.functions.getAgreement(agreement_id).call()
            return STATUS_NAMES[st], sign_count, len(parties), total

        print("после создания:", status())
        send(w3, ricardian.functions.signAgreement(agreement_id), B[1])
        print("после подписи B:", status())
        send(w3, ricardian.functions.signAgreement(agreement_id), C[1])
        st, sign_count, parties_count, total = status()
        print("после подписи C:", status())
        assert st == "active", f"ожидали active, получили {st}"
        assert sign_count == 2 and parties_count == 3

        # время за дедлайн + исполнение вехи (выплата B)
        w3.provider.make_request("evm_increaseTime", [7200])
        w3.provider.make_request("evm_mine", [])
        before_b = token.functions.balanceOf(B[0]).call()
        send(w3, ricardian.functions.executeMilestone(agreement_id, 0, B[0]), A[1])
        after_b = token.functions.balanceOf(B[0]).call()
        st, _, _, _ = status()
        ms = ricardian.functions.getMilestone(agreement_id, 0).call()
        print("после execute:", status(), "| веха completed:", ms[3])
        assert st == "completed" and ms[3] is True
        assert after_b - before_b == 1000, "выплата не совпала"
        print(f"выплата B: +{after_b - before_b} mUSDC ✔")
        print("ИТОГ: полный 2-of-3 цикл на anvil — УСПЕХ")
    finally:
        anvil.terminate()
        anvil.wait(timeout=10)


if __name__ == "__main__":
    main()
