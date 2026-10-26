"""S3: the authenticated evidence endpoint and the public offline viewer."""

from __future__ import annotations

import json
import os
import uuid

os.environ.setdefault("DEBUG", "true")

from fastapi.testclient import TestClient  # noqa: E402

from src.api import main as main_module  # noqa: E402
from src.db import database  # noqa: E402
from src.demo.app import create_app  # noqa: E402
from src.security import evidence  # noqa: E402


def _client():
    database.reset_engine()
    return TestClient(main_module.app)


def _auth(client):
    username = f"evidence-{uuid.uuid4().hex[:8]}"
    client.post("/api/v1/auth/register", json={"username": username,
                                               "password": "evidence-pass-123"})
    token = client.post("/api/v1/auth/token", json={"username": username,
                                                    "password": "evidence-pass-123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_kill_evidence_is_signed_and_shareable(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "DEFAULT_DIR", tmp_path)
    monkeypatch.setenv("SAKSHI_AUDIT_KEY", "e" * 32)
    with _client() as client:
        auth = _auth(client)
        agent = client.post("/api/v1/agents", json={"name": "evidence-agent", "tier": 1},
                            headers=auth).json()
        client.post(f"/api/v1/agents/{agent['id']}/kill-switch",
                    json={"reason": "evidence drill"}, headers=auth)
        response = client.get(f"/api/v1/agents/{agent['id']}/evidence", headers=auth)
        assert response.status_code == 200, response.text
        package = response.json()
        assert package["status"] == "killed"
        assert package["reason"] == "evidence drill"
        assert package["killed_at"] is not None
        assert any(e["event_type"] == "kill_switch" for e in package["audit_events"])
        assert evidence.verify_evidence(package) is True
        assert (tmp_path / f"{package['evidence_id']}.json").exists()

    with TestClient(create_app("")) as public:
        page = public.get(f"/evidence/{package['evidence_id']}")
        assert page.status_code == 200
        assert "VALID" in page.text
        assert package["evidence_id"] in page.text


def test_public_page_shows_invalid_after_tamper(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "DEFAULT_DIR", tmp_path)
    package = evidence.build_evidence(
        agent_id="agent-1", actor="owner", reason="drill", status="killed",
        killed_at=None, runtime_state=None, in_flight=[], audit_events=[],
        chain_valid=False,
    )
    path = evidence.save_evidence(package, directory=tmp_path)
    data = json.loads(path.read_text())
    data["reason"] = "tampered"
    path.write_text(json.dumps(data))

    with TestClient(create_app("")) as public:
        page = public.get(f"/evidence/{package['evidence_id']}")
        assert page.status_code == 200
        assert "INVALID" in page.text
