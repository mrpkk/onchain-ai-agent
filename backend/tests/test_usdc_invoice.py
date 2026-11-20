"""USDC-инвойс: создание, идемпотентность, честная проверка (26.10.2026).

Проверяем не «нажали ли кнопку», а контракт: счёт не становится оплаченным без
подтверждённой суммы, повторная проверка не оплачивает дважды, просроченный счёт
не притворяется живым.
"""

import os
import tempfile
from decimal import Decimal
from pathlib import Path

os.environ["KARTA_INVOICES_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-inv-")) / "inv.db")
os.environ["KARTA_USDC_ADDRESS"] = "0x1111111111111111111111111111111111111111"

from src.billing import usdc_invoice as inv  # noqa: E402

ADDRESS = os.environ["KARTA_USDC_ADDRESS"]


def test_create_and_read():
    item = inv.create("2500", "KARTA pilot")
    assert item["status"] == "pending"
    assert item["amount"] == "2500"
    assert item["address"] == ADDRESS
    assert item["chain"] == "base"
    assert item["payment_uri"].startswith("ethereum:0x8335")


def test_wrong_amount_does_not_pay():
    item = inv.create("2500", "pilot")
    paid = inv.verify(item["id"], "0xdead", reader=lambda tx, addr: Decimal("2499.999999"))
    assert paid["status"] == "pending", "недоплата не должна закрывать счёт"


def test_unknown_tx_does_not_pay():
    item = inv.create("2500")
    assert inv.verify(item["id"], "0xdead", reader=lambda tx, addr: None)["status"] == "pending"


def test_exact_payment_marks_paid_and_is_idempotent():
    item = inv.create("2500", "pilot")
    paid = inv.verify(item["id"], "0xabc", reader=lambda tx, addr: Decimal("2500"))
    assert paid["status"] == "paid" and paid["tx_hash"] == "0xabc"

    again = inv.verify(item["id"], "0xdef", reader=lambda tx, addr: Decimal("1"))
    assert again["status"] == "paid" and again["tx_hash"] == "0xabc", "вторая проверка не переписывает оплату"


def test_overpayment_is_accepted():
    item = inv.create("25")
    assert inv.verify(item["id"], "0x1", reader=lambda tx, addr: Decimal("26"))["status"] == "paid"


def test_expired_invoice_is_not_payable():
    item = inv.create("10", ttl_hours=1)
    # сдвигаем срок в прошлое прямо в БД — так тест не спит час
    import sqlite3
    with sqlite3.connect(os.environ["KARTA_INVOICES_DB"]) as conn:
        conn.execute("UPDATE invoices SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                     (item["id"],))
    expired = inv.verify(item["id"], "0x1", reader=lambda tx, addr: Decimal("10"))
    assert expired["status"] == "expired", "просроченный счёт не должен становиться paid"


def test_amount_validation():
    for bad in ("0", "-1", "1.1234567", "abc"):
        try:
            inv.create(bad)
        except ValueError:
            continue
        raise AssertionError(f"amount {bad!r} должен быть отклонён")


def test_chain_failure_keeps_invoice_pending():
    item = inv.create("10")

    def boom(tx, addr):
        raise RuntimeError("rpc down")

    assert inv.verify(item["id"], "0x1", reader=boom)["status"] == "pending"
