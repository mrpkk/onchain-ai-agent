from __future__ import annotations

import asyncio

from pathlib import Path

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from .models import (
    AgentCreate,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyInfo,
    AgentListResponse,
    AgentResponse,
    AgentStatus,
    AgentUpdate,
    ApprovalListResponse,
    ApprovalResponse,
    GoalRequest,
    HealthResponse,
    IntentConfirmRequest,
    IntentConfirmResponse,
    IntentPreviewResponse,
    IntentRequest,
    AuditEventResponse,
    AuditListResponse,
    DecisionListResponse,
    DecisionReplayResponse,
    DecisionResponse,
    KillSwitchRequest,
    PendingListResponse,
    PolicyFromTextResponse,
    PolicyPutRequest,
    PolicyResponse,
    PolicySimulateRequest,
    PolicySimulateResponse,
    PolicyValidateRequest,
    PolicyValidateResponse,
    RefreshRequest,
    RicardianCreateRequest,
    RicardianExecuteRequest,
    RicardianMilestoneIn,
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
from ..db import (AgentRepository, ApiKeyRepository, ApprovalRepository, DecisionRepository,
                  PolicyRepository, TransactionRepository, UserRepository, create_all, session_scope)
from ..runtime import TIER_POLICY_TEMPLATES, build_agent
from ..runtime.approvals import resolve_approval
from ..runtime.drift import detect_drift
from ..runtime.health_score import compute_health_score
from ..runtime.replay import replay_decision
from ..runtime.policy_simulator import simulate_policy_change
from ..runtime.reports import build_summary, decisions_csv, transactions_csv
from ..runtime import manager as runtime_manager
from ..integrations.agent_registry import AgentRegistryError, AgentRegistryService
from ..integrations.ricardian import RicardianError, RicardianService
from ..runtime.badges import compute_badges
from ..security.apikeys import ALLOWED_SCOPES, generate_api_key
from ..security.dharma import PolicyError, TxContext, build_default_policy, compile_yaml, evaluate
from ..agent.intent import parse_intent
from ..agent.policy_intent import build_policy_yaml, parse_policy_rule
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


from ..mcp.server import mcp_dispatcher  # noqa: E402


@_asynccontextmanager
async def _lifespan(_app: FastAPI):
    await create_all()  # dev-convenience; в прод-контуре схема ведётся Alembic
    try:
        from ..runtime.reconciliation import reconcile_on_startup

        fixed = await reconcile_on_startup()
        if fixed:
            logging.getLogger("uvicorn.error").warning(
                "Реконсиляция при старте: %d агент(ов) running→stopped", fixed
            )
    except Exception as e:  # noqa: BLE001 — не роняем старт из-за реконсиляции
        logging.getLogger("uvicorn.error").warning("Реконсиляция не выполнена: %s", e)
    telegram_task = None
    stop_event = asyncio.Event()
    try:
        from ..integrations.telegram import notifier_from_env
        from ..integrations.telegram_poller import poll_loop

        notifier = notifier_from_env()
        if notifier is not None:
            telegram_task = asyncio.create_task(poll_loop(notifier, stop_event))
            logging.getLogger("uvicorn.error").info("Telegram poller запущен")
    except Exception as e:  # noqa: BLE001 — не роняем старт из-за интеграции
        logging.getLogger("uvicorn.error").warning("Telegram poller не запущен: %s", e)
    async with mcp_dispatcher.lifespan():
        yield
    if telegram_task is not None:
        stop_event.set()
        telegram_task.cancel()


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

# MCP-сервер (S6-04): streamable HTTP (stateless) на POST /mcp
from starlette.routing import Route as _StarletteRoute  # noqa: E402


async def _mcp_forward(request: Request) -> Response:
    """Точная точка POST /mcp без redirect 307: запрос уходит в MCP-диспетчер (path → /)."""
    scope = dict(request.scope)
    scope["path"] = "/"
    messages: list[dict] = []

    async def _send(message: dict) -> None:
        messages.append(message)

    await mcp_dispatcher(scope, request.receive, _send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
    return Response(content=body, status_code=start["status"], headers=headers)


app.router.routes.append(
    _StarletteRoute("/mcp", endpoint=_mcp_forward,
                    methods=["POST", "GET", "DELETE", "OPTIONS"])
)
app.mount("/mcp", mcp_dispatcher)

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


# ── API-ключи для MCP (S6-04) ────────────────────────────────────────

@app.post("/api/v1/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    scopes = list(dict.fromkeys(body.scopes))
    if not scopes or any(s not in ALLOWED_SCOPES for s in scopes):
        raise HTTPException(status_code=422, detail=f"scopes: {list(ALLOWED_SCOPES)}")
    plain, key_hash, prefix = generate_api_key()
    async with session_scope() as session:
        key = await ApiKeyRepository(session).create(
            uuid.UUID(current_user["id"]), body.name[:64], prefix, key_hash, scopes
        )
        return ApiKeyCreated(
            id=str(key.id), name=key.name, prefix=key.prefix, scopes=scopes,
            created_at=key.created_at, key=plain,
        )


@app.get("/api/v1/api-keys", response_model=list[ApiKeyInfo])
async def list_api_keys(current_user: Annotated[dict, Depends(get_current_user)]):
    async with session_scope() as session:
        keys = await ApiKeyRepository(session).list_by_owner(uuid.UUID(current_user["id"]))
        return [
            ApiKeyInfo(
                id=str(k.id), name=k.name, prefix=k.prefix,
                scopes=(k.scopes or {}).get("list", []), created_at=k.created_at,
                last_used_at=k.last_used_at, revoked=k.revoked_at is not None,
            )
            for k in keys
        ]


@app.delete("/api/v1/api-keys/{key_id}", response_model=ApiKeyInfo)
async def revoke_api_key(
    key_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        repo = ApiKeyRepository(session)
        try:
            key = await repo.get(uuid.UUID(key_id))
        except ValueError:
            key = None
        if key is None or key.user_id != uuid.UUID(current_user["id"]):
            raise HTTPException(status_code=404, detail="API key not found")
        await repo.revoke(key)
        return ApiKeyInfo(
            id=str(key.id), name=key.name, prefix=key.prefix,
            scopes=(key.scopes or {}).get("list", []), created_at=key.created_at,
            last_used_at=key.last_used_at, revoked=True,
        )


# ── Ricardian 2-of-3 (S6-03) ─────────────────────────────────────────

def _chain_http_error(exc) -> HTTPException:  # RicardianError | AgentRegistryError
    status_map = {
        "NOT_FOUND": 404,
        "NOT_CONFIGURED": 503,
        "SIGNER_MISSING": 503,
        "MAINNET_FORBIDDEN": 403,
        "RPC_UNAVAILABLE": 503,
        "SIMULATION_REVERT": 422,
        "BAD_INPUT": 422,
    }
    return HTTPException(
        status_code=status_map.get(exc.code, 502),
        detail=f"{exc.code}: {exc.message}",
    )


@app.get("/api/v1/ricardian/wallet")
async def ricardian_wallet(current_user: Annotated[dict, Depends(get_current_user)]):
    service = RicardianService()
    return {
        "signer": service.signer_address,
        "contract": service.contract_address,
        "chain": "sepolia",
        "ready": service.signer_address is not None,
    }


@app.get("/api/v1/ricardian/agreements")
async def ricardian_list(
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: int = 20,
):
    service = RicardianService()
    try:
        agreements = await service.list_agreements(limit=max(1, min(limit, 50)))
    except RicardianError as e:
        raise _chain_http_error(e) from e
    return {"agreements": agreements, "total": len(agreements)}


@app.get("/api/v1/ricardian/agreements/{agreement_id}")
async def ricardian_detail(
    agreement_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    service = RicardianService()
    try:
        return await service.get_agreement(int(agreement_id))
    except RicardianError as e:
        raise _chain_http_error(e) from e


@app.post("/api/v1/ricardian/agreements", status_code=201)
async def ricardian_create(
    body: RicardianCreateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    service = RicardianService()
    try:
        return await service.create_agreement(
            parties=body.parties,
            token=body.token,
            milestones=[m.model_dump() for m in body.milestones],
        )
    except RicardianError as e:
        raise _chain_http_error(e) from e


@app.post("/api/v1/ricardian/agreements/{agreement_id}/sign")
async def ricardian_sign(
    agreement_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    service = RicardianService()
    try:
        return await service.sign(int(agreement_id))
    except RicardianError as e:
        raise _chain_http_error(e) from e


@app.post("/api/v1/ricardian/agreements/{agreement_id}/milestones/{index}/execute")
async def ricardian_execute(
    agreement_id: int,
    index: int,
    body: RicardianExecuteRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    service = RicardianService()
    try:
        return await service.execute_milestone(int(agreement_id), int(index), body.payee)
    except RicardianError as e:
        raise _chain_http_error(e) from e


@app.post("/api/v1/ricardian/agreements/{agreement_id}/milestones/{index}/dispute")
async def ricardian_dispute(
    agreement_id: int,
    index: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    service = RicardianService()
    try:
        return await service.dispute_milestone(int(agreement_id), int(index))
    except RicardianError as e:
        raise _chain_http_error(e) from e


# ── ERC-8004 реестр агентов (S6-01) ──────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/registry")
async def agent_registry_info(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        ref = (agent.config or {}).get("onchain") or {}
        service = AgentRegistryService()
        onchain = None
        if ref.get("agent_id") is not None:
            try:
                onchain = await service.get_agent(int(ref["agent_id"]))
            except AgentRegistryError as e:
                if e.code != "NOT_FOUND":
                    raise _chain_http_error(e) from e
        summary = await build_summary(session, agent.id)
        health = await compute_health_score(session, agent.id)
        badges = compute_badges(
            onchain=onchain, health=health, trust=summary.get("trust"), tier=int(agent.tier or 0)
        )
        return {
            "onchain": onchain,
            "badges": badges,
            "contract": service.contract_address,
            "signer": service.signer_address,
            "note": "Бейджи — только из реальных данных (реестр/health/trust/tier)",
        }


@app.post("/api/v1/agents/{agent_id}/registry", status_code=201)
async def agent_registry_register(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        ref = (agent.config or {}).get("onchain") or {}
        if ref.get("agent_id") is not None:
            raise HTTPException(status_code=409, detail="Агент уже зарегистрирован в реестре")
        service = AgentRegistryService()
        base_name = (agent.name or f"karta-{str(agent.id)[:8]}")[:60]
        onchain_name = base_name
        try:
            if await service.resolve_name(base_name) is not None:
                onchain_name = f"{base_name[:50]}-{str(agent.id)[:6]}"
            metadata_uri = (
                f"{get_settings().public_base_url}/api/v1/registry/agents/{agent.id}/metadata"
            )
            result = await service.register(onchain_name, metadata_uri)
        except AgentRegistryError as e:
            raise _chain_http_error(e) from e
        config = dict(agent.config or {})
        config["onchain"] = {
            "chain_id": result["chain_id"],
            "agent_id": result["agent_id"],
            "name": onchain_name,
            "tx_hash": result["tx_hash"],
            "metadata_uri": metadata_uri,
        }
        agent.config = config
        return result


@app.post("/api/v1/agents/{agent_id}/registry/verify")
async def agent_registry_verify(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        ref = (agent.config or {}).get("onchain") or {}
        if ref.get("agent_id") is None:
            raise HTTPException(status_code=409, detail="Агент ещё не зарегистрирован в реестре")
        service = AgentRegistryService()
        try:
            result = await service.verify(int(ref["agent_id"]))
        except AgentRegistryError as e:
            raise _chain_http_error(e) from e
        config = dict(agent.config or {})
        onchain = dict(config.get("onchain") or {})
        onchain["verified"] = True
        config["onchain"] = onchain
        agent.config = config
        return result


@app.post("/api/v1/agents/{agent_id}/registry/sync-reputation")
async def agent_registry_sync_reputation(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        ref = (agent.config or {}).get("onchain") or {}
        if ref.get("agent_id") is None:
            raise HTTPException(status_code=409, detail="Агент ещё не зарегистрирован в реестре")
        health = await compute_health_score(session, agent.id)
        service = AgentRegistryService()
        try:
            result = await service.set_reputation(int(ref["agent_id"]), int(health["score"]))
        except AgentRegistryError as e:
            raise _chain_http_error(e) from e
        return {**result, "score": health["score"]}


@app.get("/api/v1/registry/agents/{agent_id}/metadata")
async def registry_public_metadata(agent_id: str):
    """Публичный паспорт агента (metadataURI в реестре): без решений/аудита/политик."""
    async with session_scope() as session:
        try:
            aid = uuid.UUID(agent_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Agent not found") from None
        agent = await AgentRepository(session).get(aid)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        ref = (agent.config or {}).get("onchain") or {}
        return {
            "name": agent.name,
            "description": agent.description or "",
            "karta": {
                "tier": int(agent.tier or 0),
                "chain_id": agent.chain_id,
                "wallet_address": agent.wallet_address,
                "status": agent.status,
                "registered_onchain": ref.get("agent_id"),
            },
            "note": "Публичный паспорт KARTA: без решений, аудита и политик",
        }


# ── Reports / export (S4-07) ───────────────────────────────────────────

@app.get("/api/v1/agents/{agent_id}/reports/summary")
async def agent_report_summary(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        summary = await build_summary(session, agent.id)
        summary["health"] = await compute_health_score(session, agent.id)
        return summary


@app.get("/api/v1/agents/{agent_id}/export.csv")
async def agent_export_csv(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    dataset: str = "decisions",
):
    if dataset not in ("decisions", "transactions", "audit"):
        raise HTTPException(status_code=422, detail="dataset: decisions|transactions|audit")
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        if dataset == "decisions":
            rows = await DecisionRepository(session).list_for_agent(agent.id, limit=5000)
            payload = decisions_csv(rows)
        elif dataset == "transactions":
            rows = await TransactionRepository(session).list_for_agent(agent.id, limit=5000)
            payload = transactions_csv(rows)
        else:
            from ..security.sakshi import AuditKeyMissing, SakshiLog

            try:
                log = SakshiLog()
            except AuditKeyMissing:
                raise HTTPException(status_code=503, detail="Audit key is not configured")
            events = await log.list_events(session, agent_id=agent.id, limit=5000)
            payload = log.export_csv(events)
    return Response(
        content=payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="karta_{dataset}_{str(agent_id)[:8]}.csv"'},
    )


# ── Approvals: web + Telegram (S4-06) ──────────────────────────────────

def _approval_to_response(approval, decision, agent) -> ApprovalResponse:
    return ApprovalResponse(
        id=str(approval.id),
        decision_id=str(approval.decision_id) if approval.decision_id else None,
        agent_id=str(agent.id) if agent else None,
        agent_name=agent.name if agent else None,
        action=decision.action if decision else None,
        params=(decision.params or {}) if decision else {},
        reasoning=decision.reasoning if decision else None,
        status=approval.status,
        channel=approval.channel,
        ttl_until=approval.ttl_until,
        created_at=approval.created_at,
    )


@app.get("/api/v1/approvals", response_model=ApprovalListResponse)
async def list_approvals(
    current_user: Annotated[dict, Depends(get_current_user)],
    limit: int = 50,
):
    async with session_scope() as session:
        rows = await ApprovalRepository(session).list_pending_with_decision(
            uuid.UUID(current_user["id"]),
        )
        items = [_approval_to_response(a, d, ag) for a, d, ag in rows[:limit]]
    return ApprovalListResponse(approvals=items, total=len(items))


async def _resolve_approval_endpoint(approval_id: str, action: str, current_user: dict) -> dict:
    owner = uuid.UUID(current_user["id"])
    result = await resolve_approval(approval_id, action, actor_user_id=owner,
                                    require_owner=owner)
    if "error" in result:
        detail = result["error"]
        code = 409 if "already" in detail else 404 if "not found" in detail else 400
        raise HTTPException(status_code=code, detail=detail)
    return result


@app.post("/api/v1/approvals/{approval_id}/approve")
async def approve_approval(
    approval_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    return await _resolve_approval_endpoint(approval_id, "approve", current_user)


@app.post("/api/v1/approvals/{approval_id}/reject")
async def reject_approval(
    approval_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    return await _resolve_approval_endpoint(approval_id, "reject", current_user)


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


@app.get("/api/v1/agents/{agent_id}/drift")
async def agent_drift(
    agent_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Autonomy Drift Detection (S4-13): сигналы отклонений поведения."""
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        return await detect_drift(session, agent.id)


@app.get("/api/v1/decisions/{decision_id}", response_model=DecisionReplayResponse)
async def get_decision_replay(
    decision_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Decision Replay v1 (S4-14): решение + вердикт текущей политики."""
    try:
        did = uuid.UUID(decision_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Decision not found")
    async with session_scope() as session:
        decision = await DecisionRepository(session).get(did)
        if decision is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        agent = await AgentRepository(session).get(decision.agent_id)
        if agent is None or str(agent.owner_id) != current_user["id"]:
            raise HTTPException(status_code=404, detail="Decision not found")
        replay = await replay_decision(session, did)
    return DecisionReplayResponse(**replay)


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


# ── Policy from text: Intent→Guarantee (S4-10) ─────────────────────────

@app.post("/api/v1/agents/{agent_id}/policy/from-text",
          response_model=PolicyFromTextResponse)
async def policy_from_text(
    agent_id: str,
    body: IntentRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        policy_row = await PolicyRepository(session).get_active(agent.id)
        base_yaml = policy_row.dsl_yaml if policy_row else None

    try:
        rule, _result = await parse_policy_rule(body.text)
    except AllProvidersFailed as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")

    if rule.rule_type == "noop" or rule.needs_clarification:
        return PolicyFromTextResponse(
            ok=True, summary=rule.summary, confidence=rule.confidence,
            needs_clarification=True, questions=rule.questions,
            warnings=["Нужны уточнения — правило не сформировано"],
        )

    try:
        yaml_str, patch = build_policy_yaml(base_yaml, rule)
    except PolicyError as e:
        raise HTTPException(status_code=422, detail=f"Invalid rule: {e}")

    return PolicyFromTextResponse(
        ok=True, summary=rule.summary, confidence=rule.confidence,
        patch=patch, dsl_yaml=yaml_str,
        warnings=["Применение — отдельным подтверждением (PUT /policy)"],
    )


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


@app.post("/api/v1/agents/{agent_id}/policy/simulate",
          response_model=PolicySimulateResponse)
async def simulate_agent_policy(
    agent_id: str,
    body: PolicySimulateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Policy Simulator: влияние кандидата на историю решений (без применения)."""
    try:
        compile_yaml(body.dsl_yaml)
    except PolicyError as e:
        raise HTTPException(status_code=422, detail=f"Invalid policy: {e}")
    async with session_scope() as session:
        agent = await _get_owned_agent(session, agent_id, current_user)
        return await simulate_policy_change(session, agent.id, body.dsl_yaml,
                                            chain_id=agent.chain_id)


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
