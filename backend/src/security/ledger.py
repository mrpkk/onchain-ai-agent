"""Budget Ledger — атомарный резерв и списание (S2, SPEC v4 §6).

Один конверт = одна задача. Бюджет защищён транзакцией `BEGIN IMMEDIATE`:
сто параллельных запросов не могут потратить больше, чем разрешено, потому что
проверка и списание происходят в одной записи SQLite, а не в памяти процесса.

Это не кастоди: деньги не проходят через ledger, он считает разрешения.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .envelope import Envelope, SpendRequest, Verdict, evaluate
from .evidence import sign_payload


def db_path() -> Path:
    return Path(os.getenv("KARTA_LEDGER_DB",
                          str(Path.home() / ".local/share/karta-demo/ledger.db")))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS envelopes (
                envelope_id TEXT PRIMARY KEY,
                budget_total TEXT NOT NULL,
                per_call_max TEXT NOT NULL,
                calls_max INTEGER NOT NULL,
                allowlist TEXT NOT NULL,
                allow_new_payee INTEGER NOT NULL DEFAULT 0,
                allow_subscriptions INTEGER NOT NULL DEFAULT 0,
                approval_threshold TEXT,
                expires_at TEXT,
                calls_used INTEGER NOT NULL DEFAULT 0,
                spent TEXT NOT NULL DEFAULT '0',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reservations (
                receipt_id TEXT PRIMARY KEY,
                envelope_id TEXT NOT NULL,
                amount TEXT NOT NULL,
                payee TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_res_envelope ON reservations(envelope_id);
            """
        )


def _row_to_envelope(row: sqlite3.Row) -> Envelope:
    expires = row["expires_at"]
    return Envelope(
        envelope_id=row["envelope_id"],
        budget_total=Decimal(row["budget_total"]),
        per_call_max=Decimal(row["per_call_max"]),
        calls_max=row["calls_max"],
        allowlist=tuple(json.loads(row["allowlist"])),
        allow_new_payee=bool(row["allow_new_payee"]),
        allow_subscriptions=bool(row["allow_subscriptions"]),
        approval_threshold=(Decimal(row["approval_threshold"])
                            if row["approval_threshold"] else None),
        expires_at=(datetime.fromisoformat(expires) if expires else None),
    )


def create(*, budget_total: Decimal, per_call_max: Decimal, calls_max: int,
           allowlist: tuple[str, ...] = (), allow_new_payee: bool = False,
           allow_subscriptions: bool = False,
           approval_threshold: Decimal | None = None,
           ttl_hours: int = 24) -> dict:
    env = Envelope(
        budget_total=budget_total, per_call_max=per_call_max, calls_max=calls_max,
        allowlist=allowlist, allow_new_payee=allow_new_payee,
        allow_subscriptions=allow_subscriptions, approval_threshold=approval_threshold,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO envelopes (envelope_id, budget_total, per_call_max, calls_max,"
            " allowlist, allow_new_payee, allow_subscriptions, approval_threshold,"
            " expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (env.envelope_id, str(env.budget_total), str(env.per_call_max), env.calls_max,
             json.dumps(list(env.allowlist)), int(env.allow_new_payee),
             int(env.allow_subscriptions),
             str(env.approval_threshold) if env.approval_threshold is not None else None,
             env.expires_at.isoformat() if env.expires_at else None,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    return get(env.envelope_id)  # type: ignore[return-value]


def get(envelope_id: str) -> dict | None:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM envelopes WHERE envelope_id=?",
                           (envelope_id,)).fetchone()
    if row is None:
        return None
    return {
        "envelope_id": row["envelope_id"],
        "budget_total": row["budget_total"],
        "per_call_max": row["per_call_max"],
        "calls_max": row["calls_max"],
        "allowlist": json.loads(row["allowlist"]),
        "allow_new_payee": bool(row["allow_new_payee"]),
        "allow_subscriptions": bool(row["allow_subscriptions"]),
        "approval_threshold": row["approval_threshold"],
        "expires_at": row["expires_at"],
        "calls_used": row["calls_used"],
        "spent": row["spent"],
        "remaining": str(Decimal(row["budget_total"]) - Decimal(row["spent"])),
    }


def reserve(envelope_id: str, *, amount: Decimal, payee: str,
            is_subscription: bool = False) -> tuple[Verdict, dict | None]:
    """Проверить и, если можно, списать — в одной транзакции. Возвращает вердикт и квитанцию."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM envelopes WHERE envelope_id=?",
                           (envelope_id,)).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return (Verdict("BLOCK", "E00", "envelope_not_found", "—", "open_envelope"), None)

        env = _row_to_envelope(row)
        request = SpendRequest(amount=amount, payee=payee, is_subscription=is_subscription,
                               calls_so_far=row["calls_used"],
                               spent_so_far=Decimal(row["spent"]))
        verdict = evaluate(env, request)
        if verdict.verdict != "ALLOW":
            conn.execute("COMMIT")
            return verdict, None

        receipt_id = f"rc_{uuid.uuid4().hex[:16]}"
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = {"receipt_id": receipt_id, "envelope_id": envelope_id,
                   "amount": str(amount), "payee": payee, "call_no": row["calls_used"] + 1,
                   "issued_at": created}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        conn.execute(
            "UPDATE envelopes SET calls_used=calls_used+1, spent=? WHERE envelope_id=?",
            (str(Decimal(row["spent"]) + amount), envelope_id),
        )
        conn.execute(
            "INSERT INTO reservations (receipt_id, envelope_id, amount, payee, created_at,"
            " payload_sha256) VALUES (?,?,?,?,?,?)",
            (receipt_id, envelope_id, str(amount), payee, created, digest),
        )
        conn.execute("COMMIT")
        payload["payload_sha256"] = digest
        payload["signed"] = True
        payload.update(sign_payload(payload))
        return verdict, payload
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def parse_decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}: not a number") from exc
    if result < 0:
        raise ValueError(f"{field}: must be >= 0")
    return result
