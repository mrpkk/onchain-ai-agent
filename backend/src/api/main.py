from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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
    KillSwitchRequest,
    RefreshRequest,
    TokenRequest,
    TokenResponse,
    TransactionListResponse,
    TransactionResponse,
    TransactionStatus,
    UserCreate,
    UserOut,
)
from ..config.settings import get_settings, validate_security
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

settings = get_settings()

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

# ── In-memory stores (swap for real DB in production) ──────────────────

_users_db: dict[str, dict] = {}
_agents_db: dict[str, dict] = {}
_transactions_db: dict[str, list[dict]] = {}

# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(
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
        "hashed_password": hash_password(body.password),
    }
    return UserOut(id=user_id, username=body.username)


@app.post("/api/v1/auth/token", response_model=TokenResponse)
async def login(body: TokenRequest, request: Request):
    client = request.client.host if request.client else "unknown"
    if not _login_limiter.allow(client):
        raise HTTPException(status_code=429, detail="Too many login attempts, try later")
    user = _users_db.get(body.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    ok, upgraded = verify_and_upgrade(body.password, user["hashed_password"])
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if upgraded:
        user["hashed_password"] = upgraded  # миграция legacy → Argon2id
    pair, _ = _issue_token_pair(user["username"])
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
    if record.sub not in _users_db:
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
    agent["goal_context"] = body.context
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


ROOT_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🤖 OnChain AI Agent — Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#0a0e14; color:#e6edf3; min-height:100vh; }

/* ── Auth ── */
#auth-screen { display:flex; align-items:center; justify-content:center; min-height:100vh; padding:20px; }
.auth-box { background:linear-gradient(135deg,#0d1117,#161b22); border:1px solid #21262d; border-radius:20px; padding:40px; width:400px; max-width:100%; }
.auth-box h1 { font-size:1.6rem; text-align:center; background:linear-gradient(135deg,#f0f6fc,#a371f7); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:8px; }
.auth-box .sub { text-align:center; color:#8b949e; font-size:0.85rem; margin-bottom:24px; }
.auth-tabs { display:flex; gap:0; margin-bottom:24px; background:#0a0e14; border-radius:10px; padding:4px; }
.auth-tab { flex:1; text-align:center; padding:10px; border-radius:8px; cursor:pointer; font-weight:600; font-size:0.9rem; color:#8b949e; transition:all .2s; }
.auth-tab.active { background:#a371f7; color:#fff; }
.auth-form { display:none; flex-direction:column; gap:14px; }
.auth-form.active { display:flex; }
.auth-form input { padding:12px 16px; border-radius:10px; border:1px solid #21262d; background:#0a0e14; color:#e6edf3; font-size:0.9rem; outline:none; transition:border .2s; }
.auth-form input:focus { border-color:#a371f7; }
.auth-form .btn-primary { padding:12px; border-radius:10px; border:none; background:linear-gradient(135deg,#a371f7,#7c3aed); color:#fff; font-weight:600; font-size:0.95rem; cursor:pointer; transition:all .2s; }
.auth-form .btn-primary:hover { transform:translateY(-1px); box-shadow:0 8px 25px rgba(163,113,247,0.3); }
.auth-error { color:#f85149; font-size:0.82rem; text-align:center; min-height:20px; }

/* ── Dashboard (hidden by default) ── */
#dash-screen { display:none; }

/* Header */
.dash-header { display:flex; align-items:center; justify-content:space-between; padding:16px 24px; background:#0d1117; border-bottom:1px solid #21262d; position:sticky; top:0; z-index:10; }
.dash-header h2 { font-size:1.1rem; display:flex; align-items:center; gap:8px; }
.dash-header .user-info { display:flex; align-items:center; gap:12px; }
.dash-header .btn-logout { padding:6px 16px; border-radius:8px; border:1px solid #21262d; background:transparent; color:#8b949e; cursor:pointer; font-size:0.8rem; transition:all .2s; }
.dash-header .btn-logout:hover { border-color:#f85149; color:#f85149; }

/* Stats */
.stats { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; padding:24px 24px 0; max-width:1200px; margin:0 auto; }
.stat-card { background:#0d1117; border:1px solid #21262d; border-radius:12px; padding:16px; text-align:center; }
.stat-card .num { font-size:1.8rem; font-weight:700; background:linear-gradient(135deg,#f0f6fc,#a371f7); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.stat-card .label { font-size:0.8rem; color:#8b949e; margin-top:4px; }
.stat-card.green .num { background:linear-gradient(135deg,#3fb950,#2ea043); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.stat-card.red .num { background:linear-gradient(135deg,#f85149,#da3633); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.stat-card.blue .num { background:linear-gradient(135deg,#58a6ff,#1f6feb); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }

/* Controls */
.controls { display:flex; align-items:center; justify-content:space-between; padding:20px 24px 0; max-width:1200px; margin:0 auto; flex-wrap:wrap; gap:12px; }
.controls h3 { font-size:1.1rem; }
.btn-create { padding:10px 20px; border-radius:10px; border:none; background:linear-gradient(135deg,#238636,#2ea043); color:#fff; font-weight:600; font-size:0.85rem; cursor:pointer; transition:all .2s; }
.btn-create:hover { transform:translateY(-1px); box-shadow:0 8px 25px rgba(46,160,67,0.3); }

/* Agent list */
.agent-list { max-width:1200px; margin:0 auto; padding:16px 24px 40px; display:flex; flex-direction:column; gap:10px; }
.agent-row { display:flex; align-items:center; gap:14px; background:#0d1117; border:1px solid #21262d; border-radius:12px; padding:16px 20px; transition:all .2s; }
.agent-row:hover { border-color:#30363d; }
.agent-info { flex:1; min-width:0; }
.agent-info .name { font-weight:600; font-size:0.95rem; display:flex; align-items:center; gap:8px; }
.agent-info .name .status-dot { width:8px; height:8px; border-radius:50%; display:inline-block; flex-shrink:0; }
.agent-info .meta { font-size:0.78rem; color:#8b949e; margin-top:2px; display:flex; gap:12px; flex-wrap:wrap; }
.agent-actions { display:flex; gap:6px; flex-shrink:0; }
.agent-actions button { padding:6px 14px; border-radius:8px; border:1px solid #21262d; background:transparent; color:#8b949e; cursor:pointer; font-size:0.75rem; font-weight:600; transition:all .2s; white-space:nowrap; }
.agent-actions .start-btn:hover { border-color:#3fb950; color:#3fb950; }
.agent-actions .stop-btn:hover { border-color:#d29922; color:#d29922; }
.agent-actions .kill-btn:hover { border-color:#f85149; color:#f85149; }
.agent-actions .goal-btn:hover { border-color:#58a6ff; color:#58a6ff; }
.agent-actions .tx-btn:hover { border-color:#a371f7; color:#a371f7; }
.agent-empty { text-align:center; padding:40px; color:#484f58; }

/* Modal */
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:100; align-items:center; justify-content:center; padding:20px; }
.modal-overlay.show { display:flex; }
.modal { background:#161b22; border:1px solid #30363d; border-radius:16px; padding:28px; width:500px; max-width:100%; max-height:80vh; overflow-y:auto; }
.modal h3 { font-size:1.1rem; margin-bottom:16px; }
.modal label { display:block; font-size:0.82rem; color:#8b949e; margin-bottom:4px; margin-top:12px; }
.modal label:first-child { margin-top:0; }
.modal input,.modal textarea,.modal select { width:100%; padding:10px 14px; border-radius:8px; border:1px solid #21262d; background:#0a0e14; color:#e6edf3; font-size:0.9rem; outline:none; }
.modal textarea { min-height:80px; resize:vertical; font-family:inherit; }
.modal input:focus,.modal textarea:focus,.modal select:focus { border-color:#a371f7; }
.modal select option { background:#0d1117; }
.modal .modal-btns { display:flex; gap:10px; margin-top:20px; }
.modal .modal-btns button { flex:1; padding:10px; border-radius:8px; font-weight:600; font-size:0.85rem; cursor:pointer; transition:all .2s; }
.modal .btn-cancel { border:1px solid #21262d; background:transparent; color:#8b949e; }
.modal .btn-cancel:hover { border-color:#484f58; }
.modal .btn-submit { border:none; background:linear-gradient(135deg,#a371f7,#7c3aed); color:#fff; }
.modal .btn-submit:hover { transform:translateY(-1px); box-shadow:0 8px 25px rgba(163,113,247,0.3); }

/* Transaction log */
.tx-panel { display:none; position:fixed; right:0; top:0; bottom:0; width:480px; max-width:100vw; background:#161b22; border-left:1px solid #30363d; z-index:50; flex-direction:column; }
.tx-panel.show { display:flex; }
.tx-panel .tx-header { display:flex; align-items:center; justify-content:space-between; padding:16px 20px; border-bottom:1px solid #21262d; }
.tx-panel .tx-header h3 { font-size:1rem; }
.tx-panel .tx-header .close-btn { background:none; border:none; color:#8b949e; font-size:1.4rem; cursor:pointer; padding:4px 8px; border-radius:6px; }
.tx-panel .tx-header .close-btn:hover { background:#21262d; color:#e6edf3; }
.tx-panel .tx-list { flex:1; overflow-y:auto; padding:12px 20px; }
.tx-item { padding:10px 0; border-bottom:1px solid #21262d; font-size:0.82rem; }
.tx-item:last-child { border:none; }
.tx-item .tx-type { font-weight:600; color:#58a6ff; }
.tx-item .tx-hash { font-family:monospace; font-size:0.75rem; color:#8b949e; word-break:break-all; }
.tx-item .tx-time { font-size:0.72rem; color:#484f58; }
.tx-item .tx-status { display:inline-block; padding:1px 8px; border-radius:4px; font-size:0.7rem; }
.tx-status.success { background:rgba(63,185,80,0.15); color:#3fb950; }
.tx-status.pending { background:rgba(210,153,34,0.15); color:#d29922; }
.tx-status.failed { background:rgba(248,81,73,0.15); color:#f85149; }
.tx-empty { text-align:center; padding:30px; color:#484f58; font-size:0.85rem; }

/* Toast */
.toast { position:fixed; bottom:20px; right:20px; padding:12px 20px; border-radius:10px; font-size:0.85rem; font-weight:500; z-index:200; transform:translateY(20px); opacity:0; transition:all .3s; pointer-events:none; }
.toast.show { transform:translateY(0); opacity:1; }
.toast.success { background:rgba(46,160,67,0.9); color:#fff; }
.toast.error { background:rgba(248,81,73,0.9); color:#fff; }
.toast.info { background:rgba(56,139,253,0.9); color:#fff; }

@media(max-width:700px) {
  .agent-row { flex-direction:column; align-items:stretch; }
  .agent-actions { flex-wrap:wrap; }
  .stats { grid-template-columns:repeat(2,1fr); }
}
</style>
</head>
<body>

<!-- ═══ Auth Screen ═══ -->
<div id="auth-screen">
  <div class="auth-box">
    <h1>🤖 OnChain AI Agent</h1>
    <p class="sub">Платформа для управления AI-агентами</p>
    <div class="auth-tabs">
      <div class="auth-tab active" onclick="switchAuth('login')">Вход</div>
      <div class="auth-tab" onclick="switchAuth('register')">Регистрация</div>
    </div>

    <div id="login-form" class="auth-form active">
      <input id="login-username" placeholder="Имя пользователя" autocomplete="username">
      <input id="login-password" type="password" placeholder="Пароль" autocomplete="current-password">
      <div class="auth-error" id="login-error"></div>
      <button class="btn-primary" onclick="doLogin()">🔐 Войти</button>
    </div>

    <div id="register-form" class="auth-form">
      <input id="reg-username" placeholder="Имя пользователя" autocomplete="username">
      <input id="reg-password" type="password" placeholder="Пароль (мин. 8 символов)" autocomplete="new-password">
      <div class="auth-error" id="reg-error"></div>
      <button class="btn-primary" onclick="doRegister()">📝 Создать аккаунт</button>
    </div>
  </div>
</div>

<!-- ═══ Dashboard ═══ -->
<div id="dash-screen">
  <div class="dash-header">
    <h2>🤖 OnChain AI Agent</h2>
    <div class="user-info">
      <span id="dash-username" style="color:#8b949e;font-size:0.85rem;"></span>
      <a href="/docs" style="color:#58a6ff;font-size:0.8rem;text-decoration:none;">📖 API</a>
      <button class="btn-logout" onclick="doLogout()">🚪 Выйти</button>
    </div>
  </div>

  <div class="stats" id="stats-bar">
    <div class="stat-card blue"><div class="num" id="stat-total">0</div><div class="label">🤖 Всего агентов</div></div>
    <div class="stat-card green"><div class="num" id="stat-running">0</div><div class="label">✅ Активные</div></div>
    <div class="stat-card"><div class="num" id="stat-created">0</div><div class="label">⏳ Создано</div></div>
    <div class="stat-card"><div class="num" id="stat-stopped">0</div><div class="label">⏸️ Остановлено</div></div>
    <div class="stat-card red"><div class="num" id="stat-killed">0</div><div class="label">☠️ Убито</div></div>
  </div>

  <div class="controls">
    <h3>🤖 Мои агенты</h3>
    <button class="btn-create" onclick="showCreateModal()">➕ Создать агента</button>
  </div>

  <div class="agent-list" id="agent-list">
    <div class="agent-empty">Загрузка агентов...</div>
  </div>
</div>

<!-- ═══ Create Modal ═══ -->
<div class="modal-overlay" id="create-modal">
  <div class="modal">
    <h3>🤖 Создать AI-агента</h3>
    <label>Имя агента</label>
    <input id="new-name" placeholder="MarketWatcher">
    <label>Описание</label>
    <textarea id="new-desc" placeholder="Мониторинг цен BTC и алерты..."></textarea>
    <label>Стратегия</label>
    <select id="new-strategy">
      <option value="default">Default</option>
      <option value="arbitrage">Arbitrage</option>
      <option value="yield-farming">Yield Farming</option>
      <option value="monitoring">Monitoring</option>
    </select>
    <label>Chain ID</label>
    <select id="new-chain">
      <option value="1">Ethereum (1)</option>
      <option value="56">BNB Chain (56)</option>
      <option value="137">Polygon (137)</option>
      <option value="10">Optimism (10)</option>
      <option value="42161">Arbitrum (42161)</option>
    </select>
    <div class="modal-btns">
      <button class="btn-cancel" onclick="hideCreateModal()">Отмена</button>
      <button class="btn-submit" onclick="createAgent()">🚀 Создать</button>
    </div>
  </div>
</div>

<!-- ═══ Goal Modal ═══ -->
<div class="modal-overlay" id="goal-modal">
  <div class="modal">
    <h3>🎯 Поставить цель</h3>
    <label>Цель</label>
    <textarea id="goal-text" placeholder="Monitor BTC price and alert when >5% drop in 1h" style="min-height:80px;"></textarea>
    <label>Контекст (опционально)</label>
    <textarea id="goal-context" placeholder="BTC has strong support at $60k..." style="min-height:60px;"></textarea>
    <div class="modal-btns">
      <button class="btn-cancel" onclick="hideGoalModal()">Отмена</button>
      <button class="btn-submit" onclick="setGoal()">🎯 Поставить</button>
    </div>
  </div>
</div>

<!-- ═══ TX Panel ═══ -->
<div class="tx-panel" id="tx-panel">
  <div class="tx-header">
    <h3>📋 Транзакции</h3>
    <button class="close-btn" onclick="hideTxPanel()">✕</button>
  </div>
  <div class="tx-list" id="tx-list">
    <div class="tx-empty">Выберите агента для просмотра транзакций</div>
  </div>
</div>

<!-- ═══ Toast ═══ -->
<div class="toast" id="toast"></div>

<script>
// ── State ──
let TOKEN = localStorage.getItem('onchain_token') || '';
let USERNAME = localStorage.getItem('onchain_user') || '';
let AGENTS = [];
let TX_AGENT_ID = '';

// ── Init ──
if (TOKEN) { showDashboard(); }

function api(url, opts={}) {
  opts.headers = opts.headers || {};
  if (TOKEN) opts.headers['Authorization'] = 'Bearer ' + TOKEN;
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
    opts.headers['Content-Type'] = 'application/json';
  }
  return fetch(url, opts).then(r => r.json().catch(() => ({error:r.statusText})));
}

function toast(msg, type='info') {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type;
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Auth ──
function switchAuth(tab) {
  document.querySelectorAll('.auth-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.auth-form').forEach(f => f.classList.remove('active'));
  if (tab==='login') {
    document.querySelector('.auth-tab').classList.add('active');
    document.getElementById('login-form').classList.add('active');
  } else {
    document.querySelectorAll('.auth-tab')[1].classList.add('active');
    document.getElementById('register-form').classList.add('active');
  }
}

async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value.trim();
  if (!username || !password) { document.getElementById('login-error').textContent = 'Заполните все поля'; return; }
  document.getElementById('login-error').textContent = '⏳ Вход...';
  const res = await api('/api/v1/auth/token', {method:'POST', body:{username, password}});
  if (res.access_token) {
    TOKEN = res.access_token; USERNAME = username;
    localStorage.setItem('onchain_token', TOKEN);
    localStorage.setItem('onchain_user', USERNAME);
    showDashboard();
  } else {
    document.getElementById('login-error').textContent = res.detail || 'Ошибка входа';
  }
}

async function doRegister() {
  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value.trim();
  if (!username || !password) { document.getElementById('reg-error').textContent = 'Заполните все поля'; return; }
  document.getElementById('reg-error').textContent = '⏳ Регистрация...';
  const res = await api('/api/v1/auth/register', {method:'POST', body:{username, password}});
  if (res.id) {
    toast('✅ Аккаунт создан! Теперь войдите.', 'success');
    switchAuth('login');
    document.getElementById('login-username').value = username;
    document.getElementById('login-password').value = password;
    doLogin();
  } else {
    document.getElementById('reg-error').textContent = res.detail || 'Ошибка регистрации';
  }
}

function doLogout() {
  TOKEN = ''; USERNAME = '';
  localStorage.removeItem('onchain_token');
  localStorage.removeItem('onchain_user');
  document.getElementById('dash-screen').style.display = 'none';
  document.getElementById('auth-screen').style.display = 'flex';
  hideTxPanel();
}

// ── Dashboard ──
function showDashboard() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('dash-screen').style.display = 'block';
  document.getElementById('dash-username').textContent = '👤 ' + USERNAME;
  loadAgents();
}

async function loadAgents() {
  const list = document.getElementById('agent-list');
  list.innerHTML = '<div class="agent-empty">⏳ Загрузка агентов...</div>';
  const res = await api('/api/v1/agents');
  AGENTS = res.agents || [];
  renderAgents();
  updateStats();
}

function updateStats() {
  const total = AGENTS.length;
  const running = AGENTS.filter(a => a.status === 'running').length;
  const created = AGENTS.filter(a => a.status === 'created').length;
  const stopped = AGENTS.filter(a => a.status === 'stopped').length;
  const killed = AGENTS.filter(a => a.status === 'killed').length;
  document.getElementById('stat-total').textContent = total;
  document.getElementById('stat-running').textContent = running;
  document.getElementById('stat-created').textContent = created;
  document.getElementById('stat-stopped').textContent = stopped;
  document.getElementById('stat-killed').textContent = killed;
}

function statusColor(s) {
  return s==='running' ? '#3fb950' : s==='created' ? '#8b949e' : s==='stopped' ? '#d29922' : '#f85149';
}
function statusLabel(s) {
  return s==='running' ? '✅ Активен' : s==='created' ? '⏳ Создан' : s==='stopped' ? '⏸️ Остановлен' : '☠️ Убит';
}

function renderAgents() {
  const list = document.getElementById('agent-list');
  if (!AGENTS.length) {
    list.innerHTML = '<div class="agent-empty">🤖 Нет агентов. Создайте первого!</div>';
    return;
  }
  list.innerHTML = AGENTS.map(a => {
    const c = statusColor(a.status);
    const l = statusLabel(a.status);
    const isRunning = a.status === 'running';
    const isKilled = a.status === 'killed';
    return `<div class="agent-row">
      <div class="agent-info">
        <div class="name"><span class="status-dot" style="background:${c}"></span>${a.name}</div>
        <div class="meta">
          <span>${l}</span>
          <span>🔗 Chain ${a.chain_id}</span>
          <span>📋 ${a.strategy}</span>
          <span>⏱️ ${new Date(a.created_at).toLocaleString()}</span>
          ${a.goal ? '<span>🎯 ' + a.goal.slice(0, 40) + (a.goal.length>40?'...':'') + '</span>' : ''}
        </div>
      </div>
      <div class="agent-actions">
        ${!isRunning && !isKilled ? `<button class="start-btn" onclick="doAction('${a.id}','start')">▶️ Запустить</button>` : ''}
        ${isRunning ? `<button class="stop-btn" onclick="doAction('${a.id}','stop')">⏸️ Стоп</button>` : ''}
        ${!isKilled ? `<button class="kill-btn" onclick="doAction('${a.id}','kill')">☠️ Kill</button>` : ''}
        <button class="goal-btn" onclick="showGoalModal('${a.id}')">🎯 Цель</button>
        <button class="tx-btn" onclick="showTx('${a.id}')">📋 TX</button>
      </div>
    </div>`;
  }).join('');
}

async function doAction(id, action) {
  let url = `/api/v1/agents/${id}/${action}`;
  if (action === 'kill') { url = `/api/v1/agents/${id}/kill-switch`; }
  let body = undefined;
  if (action === 'kill') body = {reason:'Manual kill via dashboard'};
  const res = await api(url, {method:'POST', body});
  if (res.id) {
    toast(action === 'start' ? '✅ Агент запущен' : action === 'stop' ? '⏸️ Агент остановлен' : '☠️ Kill Switch активирован', 'success');
    loadAgents();
  } else {
    toast('❌ Ошибка: ' + (res.detail || JSON.stringify(res)), 'error');
  }
}

// ── Create Modal ──
function showCreateModal() {
  document.getElementById('create-modal').classList.add('show');
  document.getElementById('new-name').value = '';
  document.getElementById('new-desc').value = '';
  document.getElementById('new-strategy').value = 'default';
  document.getElementById('new-chain').value = '1';
  setTimeout(() => document.getElementById('new-name').focus(), 100);
}
function hideCreateModal() { document.getElementById('create-modal').classList.remove('show'); }

async function createAgent() {
  const name = document.getElementById('new-name').value.trim();
  const desc = document.getElementById('new-desc').value.trim();
  if (!name) { toast('Введите имя агента', 'error'); return; }
  const res = await api('/api/v1/agents', {method:'POST', body:{
    name,
    description: desc,
    strategy: document.getElementById('new-strategy').value,
    chain_id: parseInt(document.getElementById('new-chain').value),
    config: {}
  }});
  if (res.id) {
    toast('✅ Агент ' + name + ' создан!', 'success');
    hideCreateModal();
    loadAgents();
  } else {
    toast('❌ ' + (res.detail || 'Ошибка'), 'error');
  }
}

// ── Goal Modal ──
let GOAL_AGENT_ID = '';
function showGoalModal(id) {
  GOAL_AGENT_ID = id;
  document.getElementById('goal-modal').classList.add('show');
  document.getElementById('goal-text').value = '';
  document.getElementById('goal-context').value = '';
  const agent = AGENTS.find(a => a.id === id);
  if (agent && agent.goal) document.getElementById('goal-text').value = agent.goal;
  setTimeout(() => document.getElementById('goal-text').focus(), 100);
}
function hideGoalModal() { document.getElementById('goal-modal').classList.remove('show'); GOAL_AGENT_ID = ''; }

async function setGoal() {
  const goal = document.getElementById('goal-text').value.trim();
  if (!goal) { toast('Введите цель', 'error'); return; }
  const context = document.getElementById('goal-context').value.trim();
  const res = await api('/api/v1/agents/' + GOAL_AGENT_ID + '/goal', {method:'POST', body:{goal, context}});
  if (res.id) {
    toast('🎯 Цель поставлена!', 'success');
    hideGoalModal();
    loadAgents();
  } else {
    toast('❌ ' + (res.detail || 'Ошибка'), 'error');
  }
}

// ── Transaction Panel ──
async function showTx(agentId) {
  TX_AGENT_ID = agentId;
  document.getElementById('tx-panel').classList.add('show');
  const list = document.getElementById('tx-list');
  list.innerHTML = '<div class="tx-empty">⏳ Загрузка транзакций...</div>';
  const res = await api('/api/v1/agents/' + agentId + '/transactions');
  const txs = res.transactions || [];
  const agent = AGENTS.find(a => a.id === agentId);
  if (!txs.length) {
    list.innerHTML = '<div class="tx-empty">📭 Нет транзакций для ' + (agent ? agent.name : 'агента') + '</div>';
    return;
  }
  list.innerHTML = txs.map(tx => `
    <div class="tx-item">
      <div class="tx-type">${tx.type || 'unknown'}</div>
      <div class="tx-hash">${tx.hash || tx.tx_hash || '-'}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:4px;">
        <span class="tx-status ${(tx.status||'pending')}">${tx.status || 'pending'}</span>
        <span class="tx-time">${tx.timestamp ? new Date(tx.timestamp).toLocaleString() : ''}</span>
      </div>
    </div>
  `).join('');
}

function hideTxPanel() { document.getElementById('tx-panel').classList.remove('show'); TX_AGENT_ID = ''; }

// ── Keyboard shortcuts ──
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    hideCreateModal(); hideGoalModal(); hideTxPanel();
  }
});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root_page():
    return ROOT_HTML
