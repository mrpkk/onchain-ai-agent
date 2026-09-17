"""Guard-тест S1-04: core.py не читает приватный ключ из конфига/окружения."""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent import core  # noqa: E402

FORBIDDEN_PATTERNS = [
    "config.private_key",
    "settings.private_key",
    'os.environ["AGENT_WALLET',
    "os.getenv('AGENT_WALLET",
    'os.getenv("AGENT_WALLET',
    "agent_wallet_private_key",
]


def test_core_does_not_read_private_key_from_config():
    """Инвариант SPEC S1-04: ключ попадает в агент только через KeyVault."""
    source = inspect.getsource(core)
    for pattern in FORBIDDEN_PATTERNS:
        assert pattern not in source, f"Forbidden direct key access: {pattern}"
