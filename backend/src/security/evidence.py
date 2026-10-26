"""S3 evidence package: a signed, offline-verifiable record of a stop.

The package answers four questions without trusting the KARTA server:

* who ordered the stop and when;
* what the agent was doing at that moment (in-flight actions);
* what the Sakshi audit chain says (hashes only, no payloads);
* whether the package was changed after signing.

The Ed25519 private key lives outside the package and outside git. The public
key travels inside, so a buyer/auditor can verify offline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

VERSION = "karta-evidence-v1"
DEFAULT_DIR = Path(os.getenv("KARTA_EVIDENCE_DIR", str(Path.home() / ".local/share/karta/evidence")))
DEFAULT_KEY_FILE = Path(os.getenv("KARTA_EVIDENCE_KEY_FILE", str(Path.home() / ".config/karta/evidence.key")))
_EVIDENCE_ID = re.compile(r"^[0-9a-f]{16}$")


def canonical(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON for signing and hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def _load_private_key() -> Ed25519PrivateKey:
    raw = os.getenv("KARTA_EVIDENCE_KEY", "").strip()
    if raw:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
    if DEFAULT_KEY_FILE.exists():
        return Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(DEFAULT_KEY_FILE.read_text().strip())
        )
    key = Ed25519PrivateKey.generate()
    DEFAULT_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_KEY_FILE.write_text(base64.b64encode(key.private_bytes_raw()).decode())
    os.chmod(DEFAULT_KEY_FILE, 0o600)
    return key


def public_key_b64() -> str:
    key = _load_private_key().public_key().public_bytes_raw()
    return base64.b64encode(key).decode()


def _payload_without_signature(package: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in package.items()
            if k not in {"signature", "public_key", "algorithm", "evidence_id"}}


def _normalise_events(events: Iterable[Any]) -> list[dict[str, Any]]:
    out = []
    for event in events:
        out.append({
            "id": int(getattr(event, "id", 0)),
            "actor": str(getattr(event, "actor", "")),
            "event_type": str(getattr(event, "event_type", "")),
            "prev_hash": getattr(event, "prev_hash", None),
            "hash": getattr(event, "hash", None),
            "created_at": (
                event.created_at.isoformat()
                if getattr(event, "created_at", None) else None
            ),
        })
    return out


def _normalise_in_flight(items: Iterable[Any]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        out.append({
            "id": str(getattr(item, "id", "")),
            "action": str(getattr(item, "action", "")),
            "execute_after": (
                item.execute_after.isoformat()
                if getattr(item, "execute_after", None) else None
            ),
        })
    return out


def build_evidence(
    *,
    agent_id: str,
    actor: str,
    reason: str,
    status: str,
    killed_at: datetime | None,
    runtime_state: dict[str, Any] | None,
    in_flight: Iterable[Any] | None,
    audit_events: Iterable[Any] | None,
    chain_valid: bool,
) -> dict[str, Any]:
    """Build and sign one package. No secrets, no wallet keys, no payloads."""
    now = datetime.now(timezone.utc)
    payload = {
        "version": VERSION,
        "agent_id": str(agent_id),
        "actor": str(actor),
        "reason": str(reason or ""),
        "status": str(status),
        "killed_at": killed_at.isoformat() if killed_at else None,
        "generated_at": now.isoformat(),
        "in_flight": _normalise_in_flight(in_flight or []),
        "audit_events": _normalise_events(audit_events or []),
        "chain_valid": bool(chain_valid),
        "runtime_state": {
            k: runtime_state.get(k)
            for k in ("status", "balance", "daily_spend", "total_transactions",
                      "successful_transactions", "failed_transactions",
                      "last_action", "last_action_time")
            if runtime_state and k in runtime_state
        },
    }
    signature = _load_private_key().sign(canonical(payload))
    package = dict(payload)
    package.update({
        "signature": base64.b64encode(signature).decode(),
        "public_key": public_key_b64(),
        "algorithm": "Ed25519",
    })
    package["evidence_id"] = hashlib.sha256(canonical(package)).hexdigest()[:16]
    return package


_SIGNATURE_FIELDS = {"signature", "public_key", "algorithm"}


def sign_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Sign any canonical payload with the shared Ed25519 key. No secrets returned."""
    signature = _load_private_key().sign(canonical(payload))
    return {
        "signature": base64.b64encode(signature).decode(),
        "public_key": public_key_b64(),
        "algorithm": "Ed25519",
    }


def verify_payload(payload: dict[str, Any]) -> bool:
    """Verify a signed payload offline; signature fields are not part of the message."""
    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(payload["public_key"])
        )
        signature = base64.b64decode(payload["signature"])
        body = {k: v for k, v in payload.items() if k not in _SIGNATURE_FIELDS}
        public.verify(signature, canonical(body))
        return True
    except (KeyError, ValueError, TypeError, InvalidSignature):
        return False


def verify_evidence(package: dict[str, Any]) -> bool:
    """True only if the signature and canonical package are unchanged."""
    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(package["public_key"])
        )
        signature = base64.b64decode(package["signature"])
        payload = _payload_without_signature(package)
        public.verify(signature, canonical(payload))
        expected = hashlib.sha256(canonical({
            **payload,
            "signature": package["signature"],
            "public_key": package["public_key"],
            "algorithm": package["algorithm"],
        })).hexdigest()[:16]
        return expected == package["evidence_id"]
    except (KeyError, ValueError, TypeError, InvalidSignature):
        return False


def save_evidence(package: dict[str, Any], directory: Path | None = None) -> Path:
    target_dir = directory or DEFAULT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{package['evidence_id']}.json"
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(path, 0o644)
    return path


def load_evidence(evidence_id: str, directory: Path | None = None) -> dict[str, Any] | None:
    if not _EVIDENCE_ID.match(evidence_id or ""):
        return None
    path = (directory or DEFAULT_DIR) / f"{evidence_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ── Event bundles (S3): хеш-цепочка по записям демо/API ────────────────────
# Пакет отвечает на вопрос «что происходило и не подменили ли запись»,
# не раскрывая содержимое: только записи и их хеши.

def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Прочитать журнал событий; битые строки пропускаются, а не роняют пакет."""
    file = Path(path)
    if not file.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def build_bundle(records: Iterable[dict[str, Any]], *,
                 meta: dict[str, Any] | None = None,
                 **extra: Any) -> dict[str, Any]:
    """Собрать пакет: записи + хеш-цепочка + подпись Ed25519."""
    if extra:
        meta = {**dict(meta or {}), **extra}
    chained: list[dict[str, Any]] = []
    prev: str | None = None
    for index, record in enumerate(records):
        body = dict(record)
        body["index"] = index
        body["prev_hash"] = prev
        digest = hashlib.sha256(canonical({k: v for k, v in body.items()
                                           if k != "hash"})).hexdigest()
        body["hash"] = digest
        chained.append(body)
        prev = digest

    payload = {
        "version": VERSION,
        "kind": "event-bundle",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "meta": dict(meta or {}),
        "records": chained,
    }
    signature = _load_private_key().sign(canonical(payload))
    bundle = dict(payload)
    bundle.update({
        "record_count": len(chained),
        "signature": base64.b64encode(signature).decode(),
        "public_key": public_key_b64(),
        "algorithm": "Ed25519",
    })
    return bundle


def verify_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Проверить цепочку и подпись. Возвращает, ГДЕ порвалась цепочка."""
    records = bundle.get("records") or []
    prev: str | None = None
    for index, record in enumerate(records):
        body = dict(record)
        claimed = body.pop("hash", None)
        expected = hashlib.sha256(canonical({k: v for k, v in body.items()
                                             if k != "hash"})).hexdigest()
        if claimed != expected or body.get("prev_hash") != prev:
            return {"ok": False, "broken_at": index, "records": len(records),
                    "reason": "chain_broken"}
        prev = claimed

    payload = {k: bundle.get(k) for k in ("version", "kind", "created_at", "meta", "records")}
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(bundle["public_key"]))
        public.verify(base64.b64decode(bundle["signature"]), canonical(payload))
    except (KeyError, ValueError, TypeError):
        return {"ok": False, "broken_at": None, "records": len(records),
                "reason": "signature_invalid"}
    return {"ok": True, "broken_at": None, "records": len(records), "reason": "verified"}
