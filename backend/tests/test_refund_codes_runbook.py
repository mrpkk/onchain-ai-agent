"""Коды из runbook возврата обязаны существовать в реальной карте ошибок API."""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DOC = (BACKEND.parent / "docs" / "REFUND-RUNBOOK.md").read_text(encoding="utf-8")
MAIN = (BACKEND / "src" / "api" / "main.py").read_text(encoding="utf-8")


def _status_map() -> dict[str, int]:
    block = MAIN.split("status_map = {", 1)[1].split("}", 1)[0]
    return {m.group(1): int(m.group(2)) for m in re.finditer(r'"([A-Z_]+)":\s*(\d+)', block)}


def test_every_code_named_in_runbook_exists_in_api():
    named = set(re.findall(r"`(SIMULATION_REVERT|BAD_INPUT|EXECUTION_DISABLED|MAINNET_FORBIDDEN|"
                           r"RPC_UNAVAILABLE|SIGNER_MISSING)`", DOC))
    assert named, "runbook должен называть коды"
    mapping = _status_map()
    assert named <= set(mapping), f"в API нет: {named - set(mapping)}"


def test_runbook_says_422_is_not_retried():
    assert "**422 не повторяем**" in DOC
    assert "| 422 `SIMULATION_REVERT` |" in DOC
