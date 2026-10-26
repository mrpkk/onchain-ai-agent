"""Kill-switch KARTA (слайс S3).

Одна точка правды: пока флаг включён, ни демо, ни API, ни MCP не выдают
вердиктов — только честный отказ. Состояние в памяти процесса: остановка
мгновенная (нет сети, нет БД), но и живёт до перезапуска — это осознанно,
для публичного демо этого достаточно.
"""
from __future__ import annotations

from datetime import datetime, timezone

_state = {"active": False, "since": None, "reason": ""}


def set_active(active: bool, reason: str = "") -> dict:
    _state["active"] = bool(active)
    _state["since"] = datetime.now(timezone.utc).isoformat(timespec="seconds") if active else None
    _state["reason"] = reason if active else ""
    return status()


def is_active() -> bool:
    return bool(_state["active"])


def status() -> dict:
    return {"active": _state["active"], "since": _state["since"], "reason": _state["reason"]}


def reset() -> None:
    """Только для тестов: вернуть исходное состояние."""
    _state.update({"active": False, "since": None, "reason": ""})
