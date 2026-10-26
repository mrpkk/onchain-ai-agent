"""S6: три атаки из README воспроизводятся и остаются отказанными.

Тест не дублирует логику — он запускает те же скрипты, что читает покупатель.
Если политика ослабнет, покраснеет здесь, а не в демо.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATTACKS = ["prompt_injection_payee.py", "tool_poisoning_amount.py", "runaway_loop.py"]


def test_attacks_are_refused_by_the_envelope():
    for name in ATTACKS:
        result = subprocess.run([sys.executable, str(ROOT / "attacks" / name)],
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, f"{name} не отказан:\n{result.stdout}\n{result.stderr}"
        assert "RESULT:" in result.stdout
        assert "BLOCK" in result.stdout or "refusal" in result.stdout


def test_readme_lists_every_attack():
    readme = (ROOT / "attacks" / "README.md").read_text(encoding="utf-8")
    for name in ATTACKS:
        assert name in readme, f"{name} не описан в README"
