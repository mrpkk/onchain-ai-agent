"""Тесты S1-03: JWT access/refresh, ротация, reuse-detection, rate-limit логина."""
import os

os.environ.setdefault("DEBUG", "true")  # до импорта src.api.main (security-гейт)

import sys  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.security.tokens import (  # noqa: E402
    ACCESS,
    REFRESH,
    RefreshStore,
    TokenError,
    create_token,
    decode_token,
)
from src.api.ratelimit import SlidingWindowLimiter  # noqa: E402

SECRET = "test-secret"


# ── Токены (unit) ─────────────────────────────────────────────────────

def test_access_token_roundtrip():
    token = create_token("alice", SECRET, token_type=ACCESS, expires_delta=timedelta(minutes=15))
    payload = decode_token(token, SECRET, expected_type=ACCESS)
    assert payload["sub"] == "alice"
    assert payload["type"] == "access"


def test_expired_token_rejected():
    token = create_token("alice", SECRET, expires_delta=timedelta(seconds=-5))
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


def test_wrong_type_rejected():
    token = create_token("alice", SECRET, token_type=REFRESH, expires_delta=timedelta(days=1))
    with pytest.raises(TokenError) as exc:
        decode_token(token, SECRET, expected_type=ACCESS)
    assert exc.value.code == "TOKEN_WRONG_TYPE"


def test_tampered_token_rejected():
    token = create_token("alice", SECRET) + "x"
    with pytest.raises(TokenError):
        decode_token(token, SECRET)


# ── RefreshStore (unit) ───────────────────────────────────────────────

def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=7)


def test_store_rotate_and_reuse_flow():
    store = RefreshStore()
    store.add("j1", "fam", "alice", _future())
    assert store.is_active("j1")
    store.rotate("j1", "j2")
    assert not store.is_active("j1")
    store.add("j2", "fam", "alice", _future())
    assert store.is_active("j2")
    assert store.revoke_family("fam") == 1
    assert not store.is_active("j2")


def test_store_expired_is_inactive():
    store = RefreshStore()
    store.add("j1", "fam", "alice", datetime.now(timezone.utc) - timedelta(seconds=1))
    assert not store.is_active("j1")


def test_store_revoke_all_for_user():
    store = RefreshStore()
    store.add("a", "f1", "alice", _future())
    store.add("b", "f2", "bob", _future())
    assert store.revoke_all_for_user("alice") == 1
    assert store.is_active("b")


# ── Rate limiter (unit) ───────────────────────────────────────────────

def test_limiter_allows_up_to_max():
    limiter = SlidingWindowLimiter(max_attempts=3, window_sec=60)
    assert [limiter.allow("ip") for _ in range(4)] == [True, True, True, False]


# ── API-флоу ──────────────────────────────────────────────────────────

@pytest.fixture
def client():
    import asyncio

    from src.api import main as main_module
    from src.db import database

    database.reset_engine()
    asyncio.run(database.drop_all())
    asyncio.run(database.create_all())
    main_module._refresh_store = RefreshStore()
    main_module._login_limiter = SlidingWindowLimiter(max_attempts=5, window_sec=60)
    with TestClient(main_module.app) as test_client:
        yield test_client


def _register_and_login(client, username="alice", password="pass12345") -> dict:
    client.post("/api/v1/auth/register", json={"username": username, "password": password})
    response = client.post("/api/v1/auth/token", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def test_login_returns_pair(client):
    data = _register_and_login(client)
    assert data["access_token"] and data["refresh_token"]
    assert data["expires_in"] == 900  # access 15 минут


def test_refresh_rotates_pair(client):
    data = _register_and_login(client)
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert response.status_code == 200
    new = response.json()
    assert new["refresh_token"] != data["refresh_token"]
    me = client.get("/api/v1/agents",
                    headers={"Authorization": f"Bearer {new['access_token']}"})
    assert me.status_code == 200


def test_refresh_reuse_revokes_family(client):
    data = _register_and_login(client)
    old_refresh = data["refresh_token"]
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]

    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401  # reuse detected

    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert r3.status_code == 401  # вся семья отозвана


def test_revoke_all_kills_sessions(client):
    data = _register_and_login(client)
    response = client.post("/api/v1/auth/revoke-all",
                           headers={"Authorization": f"Bearer {data['access_token']}"})
    assert response.status_code == 200
    assert response.json()["revoked"] >= 1
    again = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert again.status_code == 401


def test_login_rate_limited(client):
    for _ in range(5):
        response = client.post("/api/v1/auth/token",
                               json={"username": "nobody", "password": "wrong-pass"})
        assert response.status_code == 401
    blocked = client.post("/api/v1/auth/token",
                          json={"username": "nobody", "password": "wrong-pass"})
    assert blocked.status_code == 429


def test_refresh_token_not_accepted_as_access(client):
    data = _register_and_login(client)
    response = client.get("/api/v1/agents",
                          headers={"Authorization": f"Bearer {data['refresh_token']}"})
    assert response.status_code == 401
