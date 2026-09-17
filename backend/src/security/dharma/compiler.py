"""Компилятор Dharma: YAML → CompiledPolicy (SPEC S1-06)."""

from __future__ import annotations

import yaml
from pydantic import ValidationError

from .dsl import CompiledPolicy, PolicyError, PolicyModel


def _parse_window(text: str | None) -> tuple[int, int] | None:
    """"HH:MM-HH:MM" → (start_min, end_min). None если не задано."""
    if not text:
        return None
    try:
        start_s, end_s = text.split("-", 1)
        sh, sm = (int(x) for x in start_s.strip().split(":"))
        eh, em = (int(x) for x in end_s.strip().split(":"))
    except (ValueError, AttributeError) as e:
        raise PolicyError(f"active_utc должен быть 'HH:MM-HH:MM': {e}") from e
    if not (0 <= sh <= 23 and 0 <= eh <= 23 and 0 <= sm <= 59 and 0 <= em <= 59):
        raise PolicyError(f"active_utc вне диапазона: {text}")
    return sh * 60 + sm, eh * 60 + em


def compile_policy(data: dict) -> CompiledPolicy:
    """Компилирует словарь политики в CompiledPolicy (fail-closed при ошибке)."""
    if not isinstance(data, dict):
        raise PolicyError("Политика должна быть словарём (mapping)")
    try:
        model = PolicyModel(**data)
    except ValidationError as e:
        raise PolicyError(f"Невалидная политика: {e}") from e
    return CompiledPolicy(model=model, window=_parse_window(model.active_utc))


def compile_yaml(text: str) -> CompiledPolicy:
    """Парсит YAML-текст и компилирует политику."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PolicyError(f"YAML-ошибка: {e}") from e
    return compile_policy(data or {})


def build_default_policy(per_tx_eth: float = 1.0, daily_eth: float = 5.0) -> CompiledPolicy:
    """Дефолтная консервативная политика из лимитов агента."""
    return compile_policy({
        "version": 1,
        "limits": {"per_tx_eth": per_tx_eth, "daily_eth": daily_eth},
        "deny": {"actions": ["deploy"]},
    })
