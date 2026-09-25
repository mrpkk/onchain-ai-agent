"""Тесты S6-04: API-ключи karta_ (выпуск/скоупы/список/отзыв)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.db import database  # noqa: E402


@pytest.fixture
def client():
    from src.api import main as main_module

    database.reset_engine()
    with TestClient(main_module.app) as test_client:
        yield test_client


def _auth_headers(client, username="keyuser", password="key-pass-123"):
    client.post("/api/v1/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/api/v1/auth/token", json={"username": username, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_api_key_lifecycle(client):
    headers = _auth_headers(client)

    created = client.post(
        "/api/v1/api-keys", json={"name": "cursor", "scopes": ["mcp:read"]}, headers=headers
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["key"].startswith("karta_")
    assert payload["prefix"].startswith("karta_")
    assert payload["scopes"] == ["mcp:read"]

    listed = client.get("/api/v1/api-keys", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "cursor"
    assert listed[0]["revoked"] is False
    assert "key" not in listed[0]  # плейн-ключ не хранится и не отдаётся

    revoke = client.delete(f"/api/v1/api-keys/{payload['id']}", headers=headers)
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True
    assert client.get("/api/v1/api-keys", headers=headers).json()[0]["revoked"] is True


def test_api_key_scope_validation(client):
    headers = _auth_headers(client, username="scopeuser")

    bad = client.post(
        "/api/v1/api-keys", json={"name": "bad", "scopes": ["admin:all"]}, headers=headers
    )
    assert bad.status_code == 422

    empty = client.post(
        "/api/v1/api-keys", json={"name": "empty", "scopes": []}, headers=headers
    )
    assert empty.status_code == 422


def test_api_key_ownership(client):
    headers_a = _auth_headers(client, username="ownera")
    headers_b = _auth_headers(client, username="ownerb")

    key = client.post(
        "/api/v1/api-keys", json={"name": "a", "scopes": ["mcp:read"]}, headers=headers_a
    ).json()

    assert client.delete(f"/api/v1/api-keys/{key['id']}", headers=headers_b).status_code == 404
    assert client.get("/api/v1/api-keys", headers=headers_b).json() == []
