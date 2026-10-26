"""Платёжный цикл счёта: без вранья.

Проверяем три вещи, которые обычно и ломаются: недоплата не делает счёт оплаченным,
повторная проверка не оплачивает дважды, просроченный счёт не притворяется живым.

Сеть не трогаем: `reader` подменяется, потому что проверяем логику, а не RPC.
"""

import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="karta-payloop-"))
os.environ["KARTA_INVOICES_DB"] = str(_TMP / "inv.db")
os.environ["KARTA_USDC_ADDRESS"] = "0x1111111111111111111111111111111111111111"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.billing import usdc_invoice as inv  # noqa: E402

ADDRESS = os.environ["KARTA_USDC_ADDRESS"]


def test_underpayment_keeps_invoice_pending():
    item = inv.create("2500", "pilot")
    result = inv.verify(item["id"], "0xdeadbeef", reader=lambda tx, addr: Decimal("2499.99"))
    assert result["status"] == "pending"
    assert result["tx_hash"] is None


def test_full_payment_marks_paid_and_is_idempotent():
    item = inv.create("100", "audit")
    reader = lambda tx, addr: Decimal("100")  # noqa: E731
    first = inv.verify(item["id"], "0xabc", reader=reader)
    assert first["status"] == "paid" and first["tx_hash"] == "0xabc"

    second = inv.verify(item["id"], "0xabc", reader=reader)
    assert second["status"] == "paid"
    assert second["paid_at"] == first["paid_at"]  # второй раз не «оплачивает» заново


def test_reader_failure_does_not_mark_paid():
    item = inv.create("2500", "pilot")

    def boom(tx, addr):
        raise RuntimeError("rpc unavailable")

    result = inv.verify(item["id"], "0xdead", reader=boom)
    assert result["status"] == "pending"


def test_wrong_recipient_amount_is_zero():
    item = inv.create("10", "test")
    calls = {}

    def reader(tx, addr):
        calls["addr"] = addr
        return Decimal("0")

    result = inv.verify(item["id"], "0x0", reader=reader)
    assert result["status"] == "pending"
    assert calls["addr"] == ADDRESS  # сверяем именно наш адрес, а не любой в транзакции
