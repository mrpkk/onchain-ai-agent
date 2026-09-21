from __future__ import annotations

from pathlib import Path

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from .models import (
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentStatus,
    AgentUpdate,
    GoalRequest,
    HealthResponse,
    IntentConfirmRequest,
    IntentConfirmResponse,
    IntentPreviewResponse,
    IntentRequest,
    AuditEventResponse,
    AuditListResponse,
    DecisionListResponse,
    DecisionResponse,
    KillSwitchRequest,
    PendingListResponse,
    PolicyPutRequest,
    PolicyResponse,
    PolicyValidateRequest,
    PolicyValidateResponse,
    RefreshRequest,
    TierRequest,
    TokenRequest,
    TokenResponse,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatus,
    UserCreate,
    UserOut,
)
from ..config.settings import get_settings, validate_security
from ..db import (AgentRepository, DecisionRepository, PolicyRepository,
                  TransactionRepository, UserRepository, create_all, session_scope)
from ..runtime import TIER_POLICY_TEMPLATES, build_agent
from ..runtime import manager as runtime_manager
from ..security.dharma import PolicyError, TxContext, build_default_policy, compile_yaml, evaluate
from ..agent.intent import parse_intent
from ..providers.llm import AllProvidersFailed
from ..security.passwords import hash_password, verify_and_upgrade
from ..security.tokens import (
    ACCESS,
    REFRESH,
    RefreshStore,
    TokenError,
    create_token,
    decode_token,
)
from .health import collect_health
from .ratelimit import SlidingWindowLimiter
from .ws import agent_event_sink
from .ws import manager as ws_manager
from .ws import router as ws_router

settings = get_settings()
STATIC_DIR = Path(__file__).parent / "static"

# RTM NFR-1: security-гейт при старте (в debug только предупреждения)
_security_issues = validate_security(settings)
if _security_issues:
    import logging
    for issue in _security_issues:
        logging.getLogger("uvicorn.error").error("SECURITY: %s", issue)
    if not settings.debug:
        raise RuntimeError(
            "Отказ запуска: нарушения безопасности: " + "; ".join(_security_issues)
        )
app_start_time = time.time()

# ── Password hashing ──────────────────────────────────────────────────
# Argon2id + миграция legacy-хешей: см. src/security/passwords.py (S1-02).
# hash_password / verify_and_upgrade импортированы из security-модуля.

# ── OAuth2 ─────────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# ── Storage: PostgreSQL через репозитории (SPEC S2-01) ─────────────────


# ── App ────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager as _asynccontextmanager


@_asynccontextmanager
async def _lifespan(_app: FastAPI):
    await create_all()  # dev-convenience; в прод-контуре схема ведётся Alembic
    yield


app = FastAPI(
    lifespan=_lifespan,
    title=settings.app_name,
    description=(
        "🤖 **OnChain AI Agent** — платформа для создания и управления "
        "автономными AI-агентами в блокчейне.\n\n"
        "**Возможности:**\n"
        "• 🔐 JWT-аутентификация (register → login → token)\n"
        "• 🤖 CRUD AI-агентов (создать, запустить, остановить, удалить)\n"
        "• 🎯 Постановка целей и контекста для агента\n"
        "• ☠️ Kill Switch — экстренная остановка агента\n"
        "• 💳 Просмотр транзакций агента\n"
        "• 🔌 REST API + Swagger документация\n\n"
        "Попробуй: `/api/v1/auth/register` → получи JWT → создай агента 🚀"
    ),
    version=settings.app_version,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.include_router(ws_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── JWT helpers ────────────────────────────────────────────────────────

_refresh_store = RefreshStore()
_login_limiter = SlidingWindowLimiter(max_attempts=5, window_sec=60.0)


def _issue_token_pair(username: str, family_id: str | None = None) -> tuple[TokenResponse, str]:
    """Выдаёт access+refresh одной семьи; возвращает пару и jti refresh-токена."""
    now = datetime.now(timezone.utc)
    access_minutes = settings.jwt_access_token_expire_minutes
    refresh_days = settings.jwt_refresh_token_expire_days
    access = create_token(username, settings.jwt_secret_key, settings.jwt_algorithm,
                          token_type=ACCESS, expires_delta=timedelta(minutes=access_minutes))
    jti = uuid.uuid4().hex
    family = family_id or uuid.uuid4().hex
    refresh = create_token(username, settings.jwt_secret_key, settings.jwt_algorithm,
                           token_type=REFRESH, expires_delta=timedelta(days=refresh_days),
                           family_id=family, jti=jti)
    _refresh_store.add(jti, family, username, now + timedelta(days=refresh_days))
    response = TokenResponse(access_token=access, refresh_token=refresh,
                             expires_in=access_minutes * 60)
    return response, jti


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, settings.jwt_secret_key, settings.jwt_algorithm,
                               expected_type=ACCESS)
        username: str | None = payload.get("sub")
    except TokenError:
        raise credentials_exc
    async with session_scope() as session:
        user = await UserRepository(session).get_by_username(username)
    if user is None:
        raise credentials_exc
    return {"id": str(user.id), "username": user.username}


# ── Auth endpoints ─────────────────────────────────────────────────────

@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
async def register(body: UserCreate):
    async with session_scope() as session:
        users = UserRepository(session)
        if await users.get_by_username(body.username) is not None:
            raise HTTPException(status_code=409, detail="Username already taken")
        user = await users.create(body.username, hash_password(body.password))
        user_id, username = user.id, user.username
    return UserOut(id=str(user_id), username=username)


@app.post("/api/v1/auth/token", response_model=TokenResponse)
async def login(body: TokenRequest, request: Request):
    client = request.client.host if request.client else "unknown"
    if not _login_limiter.allow(client):
        raise HTTPException(status_code=429, detail="Too many login attempts, try later")
    async with session_scope() as session:
        users = UserRepository(session)
        user = await users.get_by_username(body.username)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        ok, upgraded = verify_and_upgrade(body.password, user.password_hash)
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if upgraded:
            await users.update_password_hash(user, upgraded)  # миграция legacy → Argon2id
        username = user.username
    pair, _ = _issue_token_pair(username)
    return pair


@app.post("/api/v1/auth/refresh", response_model=TokenResponse)
async def refresh_tokens(body: RefreshRequest):
    """Ротация refresh-пары; повторное использование → отзыв всей семьи (S1-03)."""
    try:
        payload = decode_token(body.refresh_token, settings.jwt_secret_key,
                               settings.jwt_algorithm, expected_type=REFRESH)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    record = _refresh_store.get(payload.get("jti", ""))
    now = datetime.now(timezone.utc)
    if record is None or record.expires_at <= now:
        raise HTTPException(status_code=401, detail="Refresh token expired or unknown")
    if record.revoked:
        _refresh_store.revoke_family(record.family_id)
        logging.getLogger("uvicorn.error").warning(
            "REFRESH REUSE detected user=%s family=%s — family revoked",
            record.sub, record.family_id)
        raise HTTPException(status_code=401, detail="Refresh token reuse detected; sessions revoked")
    async with session_scope() as session:
        user = await UserRepository(session).get_by_username(record.sub)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    pair, new_jti = _issue_token_pair(record.sub, family_id=record.family_id)
    _refresh_store.rotate(record.jti, new_jti)
    return pair


@app.post("/api/v1/auth/logout")
@app.post("/api/v1/auth/revoke-all")
async def revoke_all_tokens(current_user: Annotated[dict, Depends(get_current_user)]):
    """Отзыв всех refresh-сессий пользователя."""
    revoked = _refresh_store.revoke_all_for_user(current_user["username"])
    return {"status": "ok", "revoked": revoked}


# ── Agent CRUD ─────────────────────────────────────────────────────────

def _agent_to_response(agent) -> AgentResponse:
    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        description=agent.description or "",
        strategy=agent.strategy,
        tier=int(agent.tier or 0),
        status=AgentStatus(agent.status),
        chain_id=agent.chain_id,
        wallet_address=agent.wallet_address,
        config=agent.config or {},
        goal=agent.goal_text,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _tx_to_response(tx) -> TransactionResponse:
    params = tx.params or {}
    try:
        status_value = TransactionStatus(tx.status)
    except ValueError:
        status_value = TransactionStatus.PENDING
    return TransactionResponse(
        id=str(tx.id),
        agent_id=str(tx.agent_id),
        tx_hash=tx.tx_hash,
        chain_id=tx.chain_id,
        from_address="",
        to_address=str(params.get("to", "")),
        value=str(params.get("amount", "0")),
        gas_used=tx.gas_used,
        status=status_value,
        block_number=None,
        timestamp=tx.created_at,
        metadata={"action": tx.action},
    )


async def _get_owned_agent(session, agent_id: str, current_user: dict):
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = await AgentRepository(session).get(agent_uuid)
    if agent is None or str(agent.owner_id) != current_user["id"]:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.post("/api/v1/agents", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await AgentRepository(session).create(
            owner_id=uuid.UUID(current_user["id"]),
            name=body.name,
            description=body.description,
            strategy=body.strategy,
            chain_id=body.chain_id,
            wallet_address=body.wallet_address,
            config=body.config,
            status=AgentStatus.CREATED.value,
            tier=body.tier,
        )
        dsl = TIER_POLICY_TEMPLATES.get(agent.tier)
        if dsl:
            await PolicyRepository(session).create_version(
                agent.id, dsl, _compiled_to_dict(compile_yaml(dsl)),
            )
        response = _agent_to_response(agent)
    return response


@app.get("/api/v1/agents", response_model=AgentListResponse)
async def list_agents(
    current_user: Annotated[dict, Depends(get_current_user)],
    offset: int = 0,
    limit: int = 50,
):
    async with session_scope() as session:
        repo = AgentRepository(session)
        owner = uuid.UUID(current_user["id"])
        agents = await repo.list_by_owner(owner, offset=offset, limit=limit)
        total = await repo.count_by_owner(owner)
        items = [_agent_to_response(a) for a in agents]
    return AgentListResponse(agents=items, total=total)


@app.get("/api/v1/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        response = _agent_to_response(agent)
    return response


@app.post("/api/v1/agents/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        if agent.status == AgentStatus.RUNNING.value:
            raise HTTPException(status_code=409, detail="Agent is already running")
        if agent.status == AgentStatus.KILLED.value:
            raise HTTPException(status_code=409, detail="Agent has been killed")
        await AgentRepository(session).set_status(agent, AgentStatus.RUNNING.value)
        response = _agent_to_response(agent)
        runtime = await build_agent(agent, event_sink=agent_event_sink)
    await runtime_manager.start(str(agent.id), runtime)
    await ws_manager.broadcast({"type": "agent.status", "agent_id": str(agent.id),
                                "status": AgentStatus.RUNNING.value})
    return response


@app.post("/api/v1/agents/{agent_id}/stop", response_model=AgentResponse)
async def stop_agent(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        if agent.status != AgentStatus.RUNNING.value:
            raise HTTPException(status_code=409, detail="Agent is not running")
        await AgentRepository(session).set_status(agent, AgentStatus.STOPPED.value)
        response = _agent_to_response(agent)
    await runtime_manager.stop(str(agent.id))
    await ws_manager.broadcast({"type": "agent.status", "agent_id": str(agent.id),
                                "status": AgentStatus.STOPPED.value})
    return response


@app.post("/api/v1/agents/{agent_id}/goal", response_model=AgentResponse)
async def set_goal(
    agent_id: str,
    body: GoalRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        await AgentRepository(session).set_goal(agent, body.goal, body.context)
        response = _agent_to_response(agent)
    return response


@app.post("/api/v1/agents/{agent_id}/kill-switch", response_model=AgentResponse)
async def kill_switch(
    agent_id: str,
    body: KillSwitchRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        agent.config = {**(agent.config or {}), "kill_reason": body.reason}
        await AgentRepository(session).set_status(agent, AgentStatus.KILLED.value)
        response = _agent_to_response(agent)
    runtime = runtime_manager.get(str(agent.id))
    if runtime is not None:
        runtime.trigger_kill_switch(mode="hard", reason=body.reason)
        await runtime_manager.stop(str(agent.id))
    await ws_manager.broadcast({"type": "agent.status", "agent_id": str(agent.id),
                                "status": AgentStatus.KILLED.value, "reason": body.reason})
    return response


@app.post("/api/v1/agents/{agent_id}/tier", response_model=AgentResponse)
async def set_agent_tier(
    agent_id: str,
    body: TierRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Смена trust-тира (S4-04): обновляет агента и выпускает новую политику тира."""
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        await AgentRepository(session).set_tier(agent, body.tier)
        dsl = TIER_POLICY_TEMPLATES[body.tier]
        await PolicyRepository(session).create_version(
            agent.id, dsl, _compiled_to_dict(compile_yaml(dsl)),
        )
        response = _agent_to_response(agent)
    await ws_manager.broadcast({"type": "agent.status", "agent_id": str(agent.id),
                                "status": agent.status, "tier": body.tier})
    return response


# ── Transactions ───────────────────────────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/transactions", response_model=TransactionListResponse)
async def list_transactions(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    offset: int = 0,
    limit: int = 50,
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        repo = TransactionRepository(session)
        txs = await repo.list_for_agent(agent.id, offset=offset, limit=limit)
        total = await repo.count_for_agent(agent.id)
        items = [_tx_to_response(tx) for tx in txs]
    return TransactionListResponse(transactions=items, total=total)


# ── Chat-first intent (S4-03) ──────────────────────────────────────────

@app.post("/api/v1/agents/{agent_id}/intent", response_model=IntentPreviewResponse)
async def parse_agent_intent(
    agent_id: str,
    body: IntentRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        policy_row = await PolicyRepository(session).get_active(agent.id)

    policy = compile_yaml(policy_row.dsl_yaml) if policy_row else build_default_policy()
    try:
        intent, _result = await parse_intent(body.text)
    except AllProvidersFailed as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")

    verdict = evaluate(policy, TxContext(
        action=intent.action, params=intent.params, chain_id=agent.chain_id,
        gas_price_gwei=0.0, risk_score=0.5, new_spender=False,
    ))
    warnings = [
        "Предварительная оценка: газ и история транзакций не учтены",
        "Симуляция выполняется при подтверждении (зависит от кошелька)",
    ]
    if intent.needs_clarification:
        warnings.append("Нужны уточнения — подтверждение недоступно до ответов")
    return IntentPreviewResponse(ok=True, intent=intent.model_dump(),
                                 policy_verdict=verdict.to_dict(), warnings=warnings)


@app.post("/api/v1/agents/{agent_id}/intent/confirm", response_model=IntentConfirmResponse)
async def confirm_agent_intent(
    agent_id: str,
    body: IntentConfirmRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
    runtime = runtime_manager.get(str(agent.id))
    if runtime is None:
        raise HTTPException(status_code=409, detail="Agent is not running")
    result = await runtime.execute_intent(body.action, body.params)
    return IntentConfirmResponse(
        status=result.get("status", "unknown"),
        tx_hash=result.get("tx_hash") or None,
        error=result.get("error"),
        detail=result,
    )


# ── Runtime ops: heartbeat / pending / decisions / audit (S3-06) ───────

def _decision_to_response(row) -> DecisionResponse:
    return DecisionResponse(
        id=str(row.id), action=row.action, reasoning=row.reasoning,
        confidence=row.confidence, risk_level=row.risk_level,
        policy_verdict=row.policy_verdict, requires_approval=row.requires_approval,
        status=row.status, created_at=row.created_at,
    )


async def _require_running_agent(agent_id: str, current_user: dict):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
    runtime = runtime_manager.get(str(agent.id))
    if runtime is None:
        raise HTTPException(status_code=409, detail="Agent is not running")
    return agent, runtime


@app.post("/api/v1/agents/{agent_id}/heartbeat")
async def agent_heartbeat(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    agent, runtime = await _require_running_agent(agent_id, current_user)
    runtime.heartbeat()
    return {"status": "ok", "agent_id": str(agent.id)}


@app.get("/api/v1/agents/{agent_id}/pending", response_model=PendingListResponse)
async def list_pending_actions(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    _agent, runtime = await _require_running_agent(agent_id, current_user)
    items = [p.to_dict() for p in runtime.timelock.pending()]
    return PendingListResponse(pending=items, total=len(items))


@app.post("/api/v1/agents/{agent_id}/pending/{pending_id}/cancel")
async def cancel_pending_action(
    agent_id: str,
    pending_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    _agent, runtime = await _require_running_agent(agent_id, current_user)
    if not runtime.cancel_pending(pending_id):
        raise HTTPException(status_code=404, detail="Pending action not found")
    return {"status": "ok", "cancelled": pending_id}


@app.get("/api/v1/agents/{agent_id}/decisions", response_model=DecisionListResponse)
async def list_decisions(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    offset: int = 0,
    limit: int = 50,
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        repo = DecisionRepository(session)
        rows = await repo.list_for_agent(agent.id, offset=offset, limit=limit)
        total = await repo.count_for_agent(agent.id)
        items = [_decision_to_response(row) for row in rows]
    return DecisionListResponse(decisions=items, total=total)


@app.get("/api/v1/agents/{agent_id}/audit", response_model=AuditListResponse)
async def list_audit_events(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: int = 200,
):
    from ..security.sakshi import AuditKeyMissing, SakshiLog

    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        try:
            log = SakshiLog()
        except AuditKeyMissing:
            raise HTTPException(status_code=503, detail="Audit key is not configured")
        events = await log.list_events(session, agent_id=agent.id, limit=limit)
        items = [
            AuditEventResponse(
                id=e.id, actor=e.actor, event_type=e.event_type, payload=e.payload or {},
                prev_hash=e.prev_hash, hash=e.hash, created_at=e.created_at,
            )
            for e in events
        ]
    return AuditListResponse(events=items, total=len(items))


# ── Policy (Dharma DSL, SPEC S3-01) ────────────────────────────────────

def _compiled_to_dict(compiled) -> dict:
    return {
        "version": compiled.version,
        "window": list(compiled.window) if compiled.window else None,
        "model": compiled.model.model_dump(mode="json"),
    }


def _policy_to_response(policy) -> PolicyResponse:
    return PolicyResponse(
        agent_id=str(policy.agent_id),
        version=policy.version,
        dsl_yaml=policy.dsl_yaml,
        active=policy.active,
        compiled=policy.compiled or {},
    )


@app.get("/api/v1/agents/{agent_id}/policy", response_model=PolicyResponse)
async def get_agent_policy(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        policy = await PolicyRepository(session).get_active(agent.id)
        if policy is None:
            raise HTTPException(status_code=404, detail="Policy not set for agent")
        return _policy_to_response(policy)


@app.put("/api/v1/agents/{agent_id}/policy", response_model=PolicyResponse)
async def put_agent_policy(
    agent_id: str,
    body: PolicyPutRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    try:
        compiled = compile_yaml(body.dsl_yaml)
    except PolicyError as e:
        raise HTTPException(status_code=422, detail=f"Invalid policy: {e}")
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        policy = await PolicyRepository(session).create_version(
            agent.id, body.dsl_yaml, _compiled_to_dict(compiled),
        )
        return _policy_to_response(policy)


@app.post("/api/v1/policies/validate", response_model=PolicyValidateResponse)
async def validate_policy(
    body: PolicyValidateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    try:
        compiled = compile_yaml(body.dsl_yaml)
    except PolicyError as e:
        return PolicyValidateResponse(valid=False, errors=[str(e)])
    return PolicyValidateResponse(
        valid=True,
        window=list(compiled.window) if compiled.window else None,
    )


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/api/v1/health", response_model=HealthResponse)
async def health():
    async with session_scope() as session:
        active = await AgentRepository(session).count_running()
    real = await collect_health(settings, app_start_time)
    return HealthResponse(
        status=real["status"],
        version=settings.app_version,
        uptime=real["uptime"],
        agents_active=active,
        components=real["components"],
    )


@app.get("/health")
async def root_health():
    return await collect_health(settings, app_start_time)


@app.get("/health/deep")
async def deep_health():
    real = await collect_health(settings, app_start_time)
    return {"version": settings.app_version, **real}



@app.get("/", response_class=FileResponse)
async def root_page():
    return FileResponse(STATIC_DIR / "index.html")
