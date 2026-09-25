#!/usr/bin/env python3
"""x402-демо клиент (S6-05): 402-челлендж → EIP-3009-подпись → оплата → контент.

Демо-режим, тестнет Sepolia, токен xUSDC без ценности.
Плательщик: KARTA_X402_DEMO_PAYER_KEY из ~/.env (одноразовый демо-кошелёк).

Запуск:
    backend/.venv/bin/python scripts/x402_demo_client.py [URL]
"""
import base64
import json
import os
import pathlib
import sys
import time

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from web3 import Web3

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/api/v1/x402/demo/premium"
RPC = "https://ethereum-sepolia-rpc.publicnode.com"

BALANCE_ABI = [{"type": "function", "name": "balanceOf", "stateMutability": "view",
                "inputs": [{"name": "account", "type": "address"}],
                "outputs": [{"type": "uint256"}]}]


def read_env() -> dict:
    env = {}
    for line in pathlib.Path("/home/iamthat/.env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> None:
    env = read_env()
    key = env["KARTA_X402_DEMO_PAYER_KEY"]
    if not key.startswith("0x"):
        key = "0x" + key
    payer = Account.from_key(key).address

    with httpx.Client(timeout=240) as client:
        # 1) Челлендж
        response = client.get(URL)
        print("1) без оплаты →", response.status_code)
        assert response.status_code == 402, response.text
        challenge = response.json()
        accept = challenge["accepts"][0]
        print("   требования:", json.dumps({
            "scheme": accept["scheme"], "network": accept["network"],
            "asset": accept["asset"], "payTo": accept["payTo"],
            "maxAmountRequired": accept["maxAmountRequired"],
        }, ensure_ascii=False))

        # 2) Подпись EIP-3009
        w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
        token = w3.eth.contract(address=w3.to_checksum_address(accept["asset"]), abi=BALANCE_ABI)
        balance_before_payer = token.functions.balanceOf(payer).call()
        balance_before_payto = token.functions.balanceOf(accept["payTo"]).call()

        now = int(time.time())
        authorization = {
            "from": payer,
            "to": accept["payTo"],
            "value": accept["maxAmountRequired"],
            "validAfter": "0",
            "validBefore": str(now + accept.get("maxTimeoutSeconds", 300)),
            "nonce": "0x" + os.urandom(32).hex(),
        }
        domain = {
            "name": accept["extra"]["name"],
            "version": accept["extra"]["version"],
            "chainId": w3.eth.chain_id,
            "verifyingContract": w3.to_checksum_address(accept["asset"]),
        }
        types = {
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ]
        }
        message = {
            "from": payer, "to": accept["payTo"], "value": int(accept["maxAmountRequired"]),
            "validAfter": 0, "validBefore": int(authorization["validBefore"]),
            "nonce": authorization["nonce"],
        }
        encoded = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
        signed = Account.sign_message(encoded, private_key=key)
        payload = {
            "x402Version": challenge["x402Version"],
            "scheme": accept["scheme"],
            "network": accept["network"],
            "payload": {"signature": signed.signature.hex(), "authorization": authorization},
        }
        header = base64.b64encode(json.dumps(payload).encode()).decode()
        print("2) подпись EIP-3009 создана (payer", payer[:10] + "…)")

        # 3) Оплата
        response = client.get(URL, headers={"X-PAYMENT": header})
        print("3) с оплатой →", response.status_code)
        assert response.status_code == 200, response.text
        receipt = json.loads(base64.b64decode(response.headers["X-PAYMENT-RESPONSE"]))
        print("   receipt:", json.dumps(receipt, ensure_ascii=False))
        print("   контент:", json.dumps(response.json(), ensure_ascii=False)[:180])

        # 4) Балансы
        balance_after_payer = token.functions.balanceOf(payer).call()
        balance_after_payto = token.functions.balanceOf(accept["payTo"]).call()
        delta_payer = (balance_before_payer - balance_after_payer) / 1e18
        delta_payto = (balance_after_payto - balance_before_payto) / 1e18
        print(f"4) балансы: payer -{delta_payer} xUSDC, KARTA +{delta_payto} xUSDC")
        assert delta_payer == delta_payto == 0.01

        # 5) Повтор той же подписи → отказ (replay)
        response = client.get(URL, headers={"X-PAYMENT": header})
        print("5) повтор подписи →", response.status_code, response.json().get("error", {}).get("code"))
        assert response.status_code == 402
        print("ИТОГ: x402-демо — УСПЕХ (402 → подпись → сеттлмент → контент, replay отклонён)")



if __name__ == "__main__":
    main()
