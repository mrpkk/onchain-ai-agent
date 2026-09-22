"""Runtime-слой KARTA: сборка агентов из БД и управление запущенными экземплярами."""

from .factory import CHAIN_NAMES, build_agent
from .manager import RuntimeManager, manager
from .tiers import (
    TIER_DESCRIPTIONS,
    TIER_LIMITS,
    TIER_NAMES,
    TIER_POLICY_TEMPLATES,
    tier_default_limits,
    tier_policy_template,
    tier_simulation_mode,
)

__all__ = [
    "CHAIN_NAMES",
    "RuntimeManager",
    "TIER_DESCRIPTIONS",
    "TIER_LIMITS",
    "TIER_NAMES",
    "TIER_POLICY_TEMPLATES",
    "build_agent",
    "manager",
    "tier_default_limits",
    "tier_policy_template",
    "tier_simulation_mode",
]
