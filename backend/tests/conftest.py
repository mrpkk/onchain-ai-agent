"""Общая настройка тестов KARTA: DEBUG + изолированная SQLite (не прод-PG)."""

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("TX_JITTER_MAX_SECONDS", "0")  # тесты не спят
_TEST_DB_DIR = tempfile.mkdtemp(prefix="karta-tests-")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_DIR}/test.db")
# KARTA demo: не писать в боевые файлы и не тащить состояние между тестами
os.environ.setdefault("KARTA_LEDGER_DB", f"{_TEST_DB_DIR}/karta-ledger.db")
os.environ.setdefault("KARTA_DEMO_EVENTS", f"{_TEST_DB_DIR}/karta-events.jsonl")

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
    try:
        from src.demo import app as demo_app

        demo_app._CREATES.clear()  # лимитер конвертов не должен протекать между тестами
    except Exception:
        pass
    try:
        from src.security import killswitch

        killswitch.reset()
    except Exception:
        pass
    yield
    try:
        from src.security import killswitch

        killswitch.reset()
    except Exception:
        pass
