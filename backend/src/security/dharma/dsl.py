"""Dharma DSL — декларативные модели политики (SPEC S1-06)."""

from __future__ import annotations

from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field

_FORBID_EXTRA = ConfigDict(extra="forbid")


class PolicyError(Exception):
    """Ошибка компиляции/валидации политики."""


class Velocity(BaseModel):
    model_config = _FORBID_EXTRA
    window_min: int = Field(default=60, ge=1, le=1440)
    max_tx: int = Field(default=10, ge=1, le=1000)


class Limits(BaseModel):
    model_config = _FORBID_EXTRA
    per_tx_eth: float = Field(default=1.0, ge=0)
    daily_eth: float = Field(default=5.0, ge=0)
    velocity: Velocity = Field(default_factory=Velocity)
    gas_gwei_cap: int = Field(default=100, ge=0)
    slippage_bps_max: int = Field(default=50, ge=0)


class Allow(BaseModel):
    model_config = _FORBID_EXTRA
    actions: set[str] = Field(
        default_factory=lambda: {"transfer", "contract_call", "approve", "hold", "swap"}
    )
    chains: set[int] | None = None
    protocols: set[str] | None = None
    addresses: set[str] = Field(default_factory=set)  # непусто → whitelist-only режим


class Deny(BaseModel):
    model_config = _FORBID_EXTRA
    addresses: set[str] = Field(default_factory=set)
    actions: set[str] = Field(default_factory=set)
    unlimited_approve: bool = True


class RequiredIf(BaseModel):
    model_config = _FORBID_EXTRA
    risk_score_gte: float = Field(default=0.6, ge=0, le=1)
    amount_eth_gte: float = Field(default=0.25, ge=0)
    new_spender: bool = True


class ApprovalRules(BaseModel):
    model_config = _FORBID_EXTRA
    required_if: RequiredIf = Field(default_factory=RequiredIf)
    ttl_min: int = Field(default=30, ge=1)


class CircuitBreakers(BaseModel):
    model_config = _FORBID_EXTRA
    anomaly_score_gte: float = Field(default=0.8, ge=0, le=1)
    revert_streak_gte: int = Field(default=3, ge=1)


class PolicyModel(BaseModel):
    model_config = _FORBID_EXTRA
    version: int = Field(default=1, ge=1)
    limits: Limits = Field(default_factory=Limits)
    allow: Allow = Field(default_factory=Allow)
    deny: Deny = Field(default_factory=Deny)
    approvals: ApprovalRules = Field(default_factory=ApprovalRules)
    active_utc: str | None = None  # "HH:MM-HH:MM"
    circuit_breakers: CircuitBreakers = Field(default_factory=CircuitBreakers)


@dataclass(frozen=True)
class CompiledPolicy:
    """Валидированная политика + разобранное временное окно (минуты UTC)."""

    model: PolicyModel
    window: tuple[int, int] | None  # (start_min, end_min) или None

    @property
    def version(self) -> int:
        return self.model.version
