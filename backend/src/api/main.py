from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from .models import (
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentStatus,
    AgentUpdate,
    GoalRequest,
    HealthResponse,
    KillSwitchRequest,
    TokenRequest,
    TokenResponse,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatus,
    UserCreate,
    UserOut,
)
from ..config.settings import get_settings

settings = get_settings()
app_start_time = time.time()

# ── Password hashing ──────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── OAuth2 ─────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# ── In-memory stores (swap for real DB in production) ──────────────────

_users_db: dict[str, dict] = {}
_agents_db: dict[str, dict] = {}
_transactions_db: dict[str, list[dict]] = {}

# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── JWT helpers ────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc
    user = _users_db.get(username)
    if user is None:
        raise credentials_exc
    return user


# ── Auth endpoints ─────────────────────────────────────────────────────

@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
async def register(body: UserCreate):
    if body.username in _users_db:
        raise HTTPException(status_code=409, detail="Username already taken")
    user_id = str(uuid.uuid4())
    _users_db[body.username] = {
        "id": user_id,
        "username": body.username,
        "hashed_password": pwd_context.hash(body.password),
    }
    return UserOut(id=user_id, username=body.username)


@app.post("/api/v1/auth/token", response_model=TokenResponse)
async def login(body: TokenRequest):
    user = _users_db.get(body.username)
    if not user or not pwd_context.verify(body.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["username"]})
    return TokenResponse(access_token=token)


# ── Agent CRUD ─────────────────────────────────────────────────────────

@app.post("/api/v1/agents", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    agent = {
        "id": agent_id,
        "name": body.name,
        "description": body.description,
        "strategy": body.strategy,
        "status": AgentStatus.CREATED,
        "chain_id": body.chain_id,
        "wallet_address": body.wallet_address,
        "config": body.config,
        "goal": None,
        "created_by": current_user["id"],
        "created_at": now,
        "updated_at": now,
    }
    _agents_db[agent_id] = agent
    _transactions_db[agent_id] = []
    return AgentResponse(**{k: v for k, v in agent.items() if k != "created_by"})


@app.get("/api/v1/agents", response_model=AgentListResponse)
async def list_agents(
    current_user: Annotated[dict, Depends(get_current_user)],
    offset: int = 0,
    limit: int = 50,
):
    user_agents = [a for a in _agents_db.values() if a["created_by"] == current_user["id"]]
    sliced = user_agents[offset : offset + limit]
    return AgentListResponse(
        agents=[
            AgentResponse(**{k: v for k, v in a.items() if k != "created_by"})
            for a in sliced
        ],
        total=len(user_agents),
    )


@app.get("/api/v1/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent = _agents_db.get(agent_id)
    if not agent or agent["created_by"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse(**{k: v for k, v in agent.items() if k != "created_by"})


@app.post("/api/v1/agents/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent = _agents_db.get(agent_id)
    if not agent or agent["created_by"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent["status"] == AgentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Agent is already running")
    if agent["status"] == AgentStatus.KILLED:
        raise HTTPException(status_code=409, detail="Agent has been killed")
    agent["status"] = AgentStatus.RUNNING
    agent["updated_at"] = datetime.now(timezone.utc)
    return AgentResponse(**{k: v for k, v in agent.items() if k != "created_by"})


@app.post("/api/v1/agents/{agent_id}/stop", response_model=AgentResponse)
async def stop_agent(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent = _agents_db.get(agent_id)
    if not agent or agent["created_by"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent["status"] != AgentStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Agent is not running")
    agent["status"] = AgentStatus.STOPPED
    agent["updated_at"] = datetime.now(timezone.utc)
    return AgentResponse(**{k: v for k, v in agent.items() if k != "created_by"})


@app.post("/api/v1/agents/{agent_id}/goal", response_model=AgentResponse)
async def set_goal(
    agent_id: str,
    body: GoalRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent = _agents_db.get(agent_id)
    if not agent or agent["created_by"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent["goal"] = body.goal
    agent["config"]["goal_context"] = body.context
    agent["updated_at"] = datetime.now(timezone.utc)
    return AgentResponse(**{k: v for k, v in agent.items() if k != "created_by"})


@app.post("/api/v1/agents/{agent_id}/kill-switch", response_model=AgentResponse)
async def kill_switch(
    agent_id: str,
    body: KillSwitchRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent = _agents_db.get(agent_id)
    if not agent or agent["created_by"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent["status"] = AgentStatus.KILLED
    agent["config"]["kill_reason"] = body.reason
    agent["updated_at"] = datetime.now(timezone.utc)
    return AgentResponse(**{k: v for k, v in agent.items() if k != "created_by"})


# ── Transactions ───────────────────────────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/transactions", response_model=TransactionListResponse)
async def list_transactions(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    offset: int = 0,
    limit: int = 50,
):
    agent = _agents_db.get(agent_id)
    if not agent or agent["created_by"] != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    txs = _transactions_db.get(agent_id, [])
    sliced = txs[offset : offset + limit]
    return TransactionListResponse(
        transactions=[TransactionResponse(**tx) for tx in sliced],
        total=len(txs),
    )


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/api/v1/health", response_model=HealthResponse)
async def health():
    active = sum(1 for a in _agents_db.values() if a["status"] == AgentStatus.RUNNING)
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        uptime=round(time.time() - app_start_time, 2),
        agents_active=active,
        blockchain_connected=True,
        redis_connected=True,
    )


@app.get("/health")
async def root_health():
    return {"status": "ok"}
