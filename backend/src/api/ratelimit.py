"""Rate limiting — скользящее окно (SPEC S1-03: login 5/мин).

Простой in-memory лимитер для MVP; при появлении Redis (P2) — общий бэкенд.
"""

from __future__ import annotations

import time


class SlidingWindowLimiter:
    """Ограничитель частоты: max_attempts попыток за window_sec секунд на ключ."""

    def __init__(self, max_attempts: int = 5, window_sec: float = 60.0) -> None:
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self._attempts: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        """True — попытка разрешена; False — лимит исчерпан (вызывающий отдаёт 429)."""
        now = time.monotonic()
        window_start = now - self.window_sec
        attempts = [t for t in self._attempts.get(key, []) if t >= window_start]
        if len(attempts) >= self.max_attempts:
            self._attempts[key] = attempts
            return False
        attempts.append(now)
        self._attempts[key] = attempts
        return True

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)
