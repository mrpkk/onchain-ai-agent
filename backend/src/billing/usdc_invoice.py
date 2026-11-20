"""USDC-инвойс без платёжного провайдера (26.10.2026).

Зачем: ENOT отказал в обслуживании, а карточный PSP требует KYC и может отказать
так же. Прямой USDC-перевод не требует ни того, ни другого: мы показываем адрес
и сумму, клиент платит, мы проверяем транзакцию в сети.

Границы, которые нельзя размывать:
* **Не кастодиан.** Деньги идут прямо на адрес получателя из `~/.env`; сервис
  только читает цепочку и сверяет перевод.
* **Не выдумываем оплату.** Нет транзакции или сумма меньше — статус остаётся
  `pending`, и это говорится прямо.
* **Адрес не хардкодим.** Берётся из env (`KARTA_USDC_ADDRESS`, запасной
  `WALLET_BINANCE_USDC_BASE`); без адреса создание счёта честно падает.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

USDC_DECIMALS = 6
def default_db() -> Path:
    """Путь читается на каждом вызове: тесты подменяют KARTA_INVOICES_DB после импорта."""
    return Path(os.getenv("KARTA_INVOICES_DB",
                          str(Path.home() / ".local/share/karta/invoices.db")))
ADDRESS_ENVS = ("KARTA_USDC_ADDRESS", "WALLET_BINANCE_USDC_BASE")
BASE_RPC = os.getenv("KARTA_BASE_RPC", "https://base-rpc.publicnode.com")
#: Native USDC на Base (6 знаков). Контракт публичный, не секрет.
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def recipient() -> str:
    for name in ADDRESS_ENVS:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    raise RuntimeError(
        "USDC-адрес не задан: положи KARTA_USDC_ADDRESS или WALLET_BINANCE_USDC_BASE в ~/.env"
    )


def _db() -> sqlite3.Connection:
    path = default_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            amount TEXT NOT NULL,
            memo TEXT NOT NULL,
            chain TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL,
            tx_hash TEXT,
            paid_at TEXT
        )
        """
    )
    return conn


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount: not a number") from exc
    if amount <= 0:
        raise ValueError("amount: must be > 0")
    if -amount.as_tuple().exponent > USDC_DECIMALS:
        raise ValueError("amount: at most 6 decimals for USDC")
    return amount


def create(amount: object, memo: str = "", ttl_hours: int = 72,
           address: str | None = None) -> dict:
    """Создать счёт. Возвращает его как словарь (это же уходит клиенту)."""
    value = _amount(amount)
    addr = address or recipient()
    invoice_id = "inv_" + uuid.uuid4().hex[:16]
    created = _now()
    expires = created + timedelta(hours=max(1, ttl_hours))
    with _db() as conn:
        conn.execute(
            "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?)",
            (invoice_id, str(value), memo, "base", addr,
             created.isoformat(timespec="seconds"), expires.isoformat(timespec="seconds"),
             "pending", None, None),
        )
    return get(invoice_id) or {}


def get(invoice_id: str) -> dict | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["payment_uri"] = f"ethereum:{USDC_BASE}@8453/transfer?address={item['address']}"
    return item


def verify(invoice_id: str, tx_hash: str, reader=None) -> dict:
    """Сверить транзакцию. `reader(tx_hash, address) -> Decimal | None`."""
    invoice = get(invoice_id)
    if invoice is None:
        raise KeyError("invoice not found")
    if invoice["status"] == "paid":
        return invoice  # идемпотентно: повторная проверка не «оплачивает» дважды
    if _now() > datetime.fromisoformat(invoice["expires_at"]):
        with _db() as conn:
            conn.execute("UPDATE invoices SET status='expired' WHERE id=?", (invoice_id,))
        return get(invoice_id) or invoice

    try:
        paid = (reader or onchain_paid)(tx_hash, invoice["address"])
    except Exception:  # noqa: BLE001 — сеть/битый хэш: счёт остаётся pending, без вранья
        paid = None
    if paid is not None and paid >= Decimal(invoice["amount"]):
        with _db() as conn:
            conn.execute(
                "UPDATE invoices SET status='paid', tx_hash=?, paid_at=? WHERE id=?",
                (tx_hash, _now().isoformat(timespec="seconds"), invoice_id),
            )
    return get(invoice_id) or invoice


def onchain_paid(tx_hash: str, address: str) -> Decimal | None:
    """Сколько USDC пришло на адрес в этой транзакции. Читает цепочку, не верит словам."""
    from web3 import Web3  # локальный импорт: CLI без сети не тянет web3

    w3 = Web3(Web3.HTTPProvider(BASE_RPC, request_kwargs={"timeout": 20}))
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    if receipt is None or receipt.get("status") != 1:
        return None
    transfer_topic = w3.keccak(text="Transfer(address,address,uint256)").hex()
    target = address.lower().replace("0x", "").rjust(64, "0")
    total = Decimal(0)
    for log in receipt.get("logs") or []:
        topics = [t.hex() if hasattr(t, "hex") else str(t) for t in log.get("topics") or []]
        contract = (log.get("address") or "").lower()
        if contract != USDC_BASE.lower():
            continue
        if not topics or topics[0].lower().removeprefix("0x") != transfer_topic.removeprefix("0x"):
            continue
        if len(topics) < 3 or topics[2].lower().removeprefix("0x")[-64:] != target:
            continue
        data = log.get("data") or "0x0"
        raw = int(data.hex() if hasattr(data, "hex") else data, 16)
        total += Decimal(raw) / (Decimal(10) ** USDC_DECIMALS)
    return total if total > 0 else None
