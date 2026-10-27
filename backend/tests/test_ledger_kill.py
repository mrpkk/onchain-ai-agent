"""Остановка конверта: запись должна ЖИТЬ, а не «выглядеть успешной».

Регрессия 27.10: `INSERT OR IGNORE` молча глотал NOT NULL по старой колонке `actor`,
функция возвращала «stopped: true», а строка не сохранялась — и списание после kill проходило.
"""

import os
import sqlite3
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

os.environ["KARTA_LEDGER_DB"] = str(Path(tempfile.mkdtemp(prefix="karta-kill-")) / "ledger.db")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.security import ledger  # noqa: E402

ledger.init()


def _open(budget: str = "1", per_call: str = "0.1") -> str:
    return ledger.create(budget_total=Decimal(budget), per_call_max=Decimal(per_call),
                         calls_max=10, allowlist=("api.example.com",))["envelope_id"]


def test_kill_is_persisted_and_visible_from_a_new_connection():
    eid = _open()
    assert ledger.kill(eid, reason="drill") is not None
    with sqlite3.connect(ledger.db_path()) as conn:
        rows = conn.execute("select reason, actor from kills where envelope_id=?",
                            (eid,)).fetchall()
    assert rows and rows[0][1], "kill должен сохраняться с автором записи"


def test_spend_after_kill_is_blocked_with_e08():
    eid = _open()
    verdict, receipt = ledger.reserve(eid, amount=Decimal("0.1"), payee="api.example.com")
    assert verdict.verdict == "ALLOW"

    ledger.kill(eid, reason="runaway loop")
    blocked, no_receipt = ledger.reserve(eid, amount=Decimal("0.1"), payee="api.example.com")
    assert (blocked.verdict, blocked.rule) == ("BLOCK", "E08")
    assert no_receipt is None

    state = ledger.get(eid)
    assert state["spent"] == "0.1"  # после остановки бюджет не тронут


def test_kill_keeps_the_first_reason():
    eid = _open()
    ledger.kill(eid, reason="first")
    ledger.kill(eid, reason="second")
    with sqlite3.connect(ledger.db_path()) as conn:
        reason = conn.execute("select reason from kills where envelope_id=?", (eid,)).fetchone()[0]
    assert reason == "first"


def test_kill_unknown_envelope_returns_none():
    assert ledger.kill("env_missing", reason="x") is None


def test_evidence_pack_contains_spend_stop_and_reproducible_hash():
    import hashlib
    import json

    eid = _open()
    ledger.reserve(eid, amount=Decimal("0.1"), payee="api.example.com")
    ledger.kill(eid, reason="audit")

    pack = ledger.evidence(eid)
    assert pack["totals"]["reservations"] == 1
    assert pack["kill"]["reason"] == "audit"

    claimed = pack.pop("payload_sha256")
    canonical = json.dumps(pack, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == claimed
