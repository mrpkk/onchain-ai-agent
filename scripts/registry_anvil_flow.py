#!/usr/bin/env python3
"""Полный цикл ERC-8004-реестра на локальном anvil (S6-01, бесплатно).

Сценарий: deploy → registerAgent → verifyAgent → updateReputation → чтение.
Запуск (из корня репозитория):
    backend/.venv/bin/python scripts/registry_anvil_flow.py
"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from web3 import Web3  # noqa: E402

from src.integrations.agent_registry import REGISTRY_ABI  # noqa: E402

ANVIL_BIN = pathlib.Path.home() / ".foundry" / "bin" / "anvil"
RPC = "http://127.0.0.1:8547"
OWNER = ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
         "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")


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
        [str(ANVIL_BIN), "--port", "8547", "--silent"],
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

        artifact = load_artifact("AgentRegistry")
        factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        receipt = send(w3, factory.constructor(), OWNER[1])
        registry = w3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"])
        print("AgentRegistry:", receipt.contractAddress)

        receipt = send(w3, registry.functions.registerAgent("karta-anvil-bot", "https://karta.local/passport.json"), OWNER[1])
        agent_id = registry.functions.resolveName("karta-anvil-bot").call()
        print(f"registerAgent: id={agent_id} tx={receipt.transactionHash.hex()[:14]}…")

        record = registry.functions.getAgent(agent_id).call()
        assert record[0] == "karta-anvil-bot" and record[4] is False and record[5] == 0
        print("до verify:", {"name": record[0], "verified": record[4], "reputation": record[5]})

        send(w3, registry.functions.verifyAgent(agent_id), OWNER[1])
        send(w3, registry.functions.updateReputation(agent_id, 87), OWNER[1])
        record = registry.functions.getAgent(agent_id).call()
        print("после verify+rep:", {"verified": record[4], "reputation": record[5]})
        assert record[4] is True and record[5] == 87

        mine = registry.functions.getAgentsByOwner(OWNER[0]).call()
        assert mine == [agent_id]
        print("ИТОГ: ERC-8004 цикл на anvil — УСПЕХ (register → verify → reputation 87)")
    finally:
        anvil.terminate()
        anvil.wait(timeout=10)


if __name__ == "__main__":
    main()
