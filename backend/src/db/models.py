"""SQLAlchemy-модели KARTA (SPEC S2-01, §6.1): 14 таблиц.

Кросс-диалектность: UUID/JSON работают и на PostgreSQL (JSONB), и в SQLite
(тестовый фолбэк). Enum-поля — String с документированными значениями.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    role: Mapped[str] = mapped_column(sa.String(20), default="user")  # user|admin|operator|agent
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(128), index=True)
    family_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)
    key_hash: Mapped[str] = mapped_column(sa.String(128), unique=True)
    scopes: Mapped[dict] = mapped_column(JSONType, default=dict)
    last_used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    strategy: Mapped[str] = mapped_column(sa.String(64), default="default")
    status: Mapped[str] = mapped_column(sa.String(20), default="created", index=True)
    chain_id: Mapped[int] = mapped_column(sa.Integer, default=1)
    wallet_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    goal_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    goal_structured: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    tier: Mapped[int] = mapped_column(sa.SmallInteger, default=0)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("agents.id"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16), default="executor")  # owner|executor|session
    chain_id: Mapped[int] = mapped_column(sa.Integer, default=1)
    address: Mapped[str] = mapped_column(sa.String(64))
    custody: Mapped[str] = mapped_column(sa.String(16), default="keyvault")  # keyvault|tee|hsm|external
    pubkey: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class SessionKey(Base):
    __tablename__ = "session_keys"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("wallets.id"), index=True)
    scope: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(sa.String(16), default="active")  # active|revoked|expired
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    dsl_yaml: Mapped[str] = mapped_column(sa.Text)
    compiled: Mapped[dict] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("agents.id"), index=True)
    goal: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.String(20), default="pending")
    steps: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("agents.id"), index=True)
    goal: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    action: Mapped[str] = mapped_column(sa.String(32))
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    reasoning: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    alternatives: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    policy_verdict: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    simulation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    data_as_of: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    requires_approval: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    status: Mapped[str] = mapped_column(sa.String(20), default="proposed")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow, index=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("agents.id"), index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("decisions.id"), nullable=True)
    chain_id: Mapped[int] = mapped_column(sa.Integer, default=1)
    tx_hash: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    nonce: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    action: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(sa.String(20), default="simulated", index=True)
    gas_used: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    gas_price_gwei: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    slippage_bps: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    simulated: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
        primary_key=True, autoincrement=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("agents.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(sa.String(16), default="system")  # user|agent|system|policy
    event_type: Mapped[str] = mapped_column(sa.String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow, index=True)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("decisions.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(sa.String(16), default="web")  # web|telegram|api
    status: Mapped[str] = mapped_column(sa.String(16), default="pending", index=True)
    ttl_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("agents.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(sa.String(32))  # anomaly|slippage|counterparty|circuit_breaker
    score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow)


class ProviderHealth(Base):
    __tablename__ = "provider_health"

    provider: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    kind: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), default="ok")  # ok|degraded|down
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    last_check: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
