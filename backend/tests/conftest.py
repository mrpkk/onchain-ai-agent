"""Общая настройка тестов KARTA: DEBUG + изолированная SQLite (не прод-PG)."""

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DEBUG", "true")
_TEST_DB_DIR = tempfile.mkdtemp(prefix="karta-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_DIR}/test.db")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_api_state():
    """Изоляция модульного состояния API между тестами (rate-limiter, refresh-store)."""
    try:
        from src.api import main as main_module
        from src.api.ratelimit import SlidingWindowLimiter
        from src.security.tokens import RefreshStore

        main_module._login_limiter = SlidingWindowLimiter(max_attempts=5, window_sec=60)
        main_module._refresh_store = RefreshStore()
    except Exception:
        pass
    yield
