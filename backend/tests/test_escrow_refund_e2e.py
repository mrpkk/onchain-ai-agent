"""Возврат и отказ на настоящей цепи: anvil + развёрнутый Escrow, без мока сервиса.

Зачем отдельный файл. До 26.11.2026 возврат проверялся только моками
(`test_refund_runbook.py` подменяет `EscrowService.refund`), то есть проверял API, а не
контракт и не баланс. Здесь исполняется `scripts/escrow_anvil_flow.py` — три сценария:
release, dispute+resolve и **refund** — и проверяется, что деньги вернулись заказчику.

Запуск: `pytest -m slow backend/tests/test_escrow_refund_e2e.py`
Без `anvil` или артефактов — skip, а не зелёный тест на пустом месте.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "escrow_anvil_flow.py"
ARTIFACTS = ROOT / "smart-contracts" / "artifacts" / "contracts"
VENV_PY = ROOT / "backend" / "venv" / "bin" / "python"


def _python() -> str:
    return str(VENV_PY) if VENV_PY.is_file() else "python3"


@pytest.mark.slow
def test_refund_returns_money_on_a_real_chain():
    if shutil.which("anvil") is None and not (Path.home() / ".foundry" / "bin" / "anvil").is_file():
        pytest.skip("anvil не установлен")
    if not (ARTIFACTS / "Escrow.sol").is_dir():
        pytest.skip("нет артефактов Escrow — сначала forge build")
    proc = subprocess.run([_python(), str(SCRIPT)], cwd=ROOT, capture_output=True,
                          text=True, timeout=600)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-800:]
    assert "ИТОГ: Escrow-цикл на anvil — УСПЕХ" in out, out[-800:]
    assert "3) refund: ('refunded', 3000)" in out, "возврат не вернул сумму заказчику"
    # Отказ: после возврата release невозможен, после спора — refund. Деньги не двигаются.
    assert "4) отказ release после refund" in out and "агенту + 0" in out
    assert "5) отказ refund после dispute" in out and "заказчику + 0" in out
