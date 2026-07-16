from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    KILLED = "killed"
    ERROR = "error"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


# ── Auth ───────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class UserOut(BaseModel):
    id: str
    username: str


# ── Agent ──────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    strategy: str = "default"
    chain_id: int = 1
    wallet_address: Optional[str] = None
    config: dict = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    strategy: Optional[str] = None
    config: Optional[dict] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    strategy: str
    status: AgentStatus
    chain_id: int
    wallet_address: Optional[str] = None
    config: dict = Field(default_factory=dict)
    goal: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    total: int


class GoalRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=2048)
    context: dict = Field(default_factory=dict)


class KillSwitchRequest(BaseModel):
    reason: str = "manual shutdown"


# ── Transactions ───────────────────────────────────────────────────────

class TransactionResponse(BaseModel):
    id: str
    agent_id: str
    tx_hash: Optional[str] = None
    chain_id: int
    from_address: str
    to_address: str
    value: str = "0"
    gas_used: Optional[int] = None
    status: TransactionStatus
    block_number: Optional[int] = None
    timestamp: datetime
    metadata: dict = Field(default_factory=dict)


class TransactionListResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int


# ── Health ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    uptime: float
    agents_active: int
    blockchain_connected: bool
    redis_connected: bool
