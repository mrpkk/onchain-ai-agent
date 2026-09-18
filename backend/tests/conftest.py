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
