"""S3: signed evidence package — offline verification and tamper detection."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("KARTA_EVIDENCE_KEY", base64.b64encode(b"k" * 32).decode())

from src.security import evidence  # noqa: E402


def test_build_and_verify_offline():
    package = evidence.build_evidence(
        agent_id="agent-1",
        actor="owner",
        reason="drill",
        status="killed",
        killed_at=datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc),
        runtime_state={"status": "killed", "balance": 1.0},
        in_flight=[],
        audit_events=[],
        chain_valid=True,
    )
    assert evidence.verify_evidence(package) is True
    assert package["algorithm"] == "Ed25519"
    assert package["public_key"] and package["signature"]
    assert "private" not in json.dumps(package).lower()


def test_tamper_breaks_signature():
    package = evidence.build_evidence(
        agent_id="agent-1", actor="owner", reason="drill", status="killed",
        killed_at=None, runtime_state=None, in_flight=[], audit_events=[],
        chain_valid=False,
    )
    package["reason"] = "changed after signing"
    assert evidence.verify_evidence(package) is False


def test_save_and_load_roundtrip(tmp_path):
    package = evidence.build_evidence(
        agent_id="agent-2", actor="owner", reason="stop", status="killed",
        killed_at=None, runtime_state=None, in_flight=[], audit_events=[],
        chain_valid=False,
    )
    path = evidence.save_evidence(package, directory=tmp_path)
    assert path.exists()
    loaded = evidence.load_evidence(package["evidence_id"], directory=tmp_path)
    assert loaded == package
    assert evidence.verify_evidence(loaded) is True


def test_unknown_or_traversal_id_returns_none(tmp_path):
    assert evidence.load_evidence("../../etc/passwd", directory=tmp_path) is None
    assert evidence.load_evidence("deadbeefdeadbeef", directory=tmp_path) is None
