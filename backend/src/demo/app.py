"""Публичное демо KARTA «политика решает» (S1, SPEC v4 §8).

Одна страница, четыре сценария, ни одного реального платежа. Вердикт выдаёт
тот же evaluator, что используют API и MCP (`src/security/envelope.py`).
Метрики — свой JSONL, без внешней аналитики: считаем не «просмотры», а
дошедших до вердикта, с меткой канала `?ref=`.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from ..security import evidence, killswitch, ledger
from ..security.envelope import Envelope, SpendRequest, evaluate

PREFIX = os.getenv("KARTA_PREFIX", "").rstrip("/")
EVENTS = Path(os.getenv("KARTA_DEMO_EVENTS",
                        str(Path.home() / ".local/share/karta-demo/events.jsonl")))
NOW = datetime.now(timezone.utc)

# Сценарии — из реальных случаев (SPEC v4 §2.2), не выдуманные.
SCENARIOS: dict[str, dict] = {
    "runaway": {
        "title": "41 000 оплачиваемых вызовов за выходные",
        "note": "Баг пагинации. Каждый платёж корректен. Лимит на вызов ничего не ловит.",
        "envelope": Envelope(
            budget_total=Decimal("2500"), per_call_max=Decimal("0.05"), calls_max=2000,
            allowlist=("api.marketdata.example",),
            expires_at=NOW + timedelta(days=2),
        ),
        "request": SpendRequest(amount=Decimal("0.05"), payee="api.marketdata.example",
                                calls_so_far=41000, spent_so_far=Decimal("2050")),
    },
    "new_payee": {
        "title": "Новый получатель на $940",
        "note": "Текст со скрейпленной страницы предложил купить отчёт у неизвестного вендора.",
        "envelope": Envelope(
            budget_total=Decimal("1000"), per_call_max=Decimal("1000"), calls_max=50,
            allowlist=("api.marketdata.example",),
            approval_threshold=Decimal("25"),
            expires_at=NOW + timedelta(days=2),
        ),
        "request": SpendRequest(amount=Decimal("940"), payee="reports-vendor.xyz",
                                calls_so_far=12, spent_so_far=Decimal("3.20")),
    },
    "subscription": {
        "title": "Подписка со скидкой 30 %",
        "note": "Инструкция «минимизируй расходы» — не разрешение на регулярный платёж.",
        "envelope": Envelope(
            budget_total=Decimal("50"), per_call_max=Decimal("10"), calls_max=200,
            allowlist=("api.marketdata.example",),
            expires_at=NOW + timedelta(days=2),
        ),
        "request": SpendRequest(amount=Decimal("9"), payee="api.marketdata.example",
                                is_subscription=True, calls_so_far=4, spent_so_far=Decimal("0.20")),
    },
    "allow": {
        "title": "Обычный вызов в рамках задачи",
        "note": "Правило не «запрещай всё»: внутри конверта действие проходит сразу.",
        "envelope": Envelope(
            budget_total=Decimal("50"), per_call_max=Decimal("0.05"), calls_max=2000,
            allowlist=("api.marketdata.example",),
            expires_at=NOW + timedelta(days=2),
        ),
        "request": SpendRequest(amount=Decimal("0.04"), payee="api.marketdata.example",
                                calls_so_far=15, spent_so_far=Decimal("0.75")),
    },
}


def _record(payload: dict) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _totals() -> dict:
    if not EVENTS.exists():
        return {"checks": 0, "by_verdict": {}, "by_ref": {}}
    by_verdict: dict[str, int] = {}
    by_ref: dict[str, int] = {}
    checks = 0
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        checks += 1
        by_verdict[e.get("verdict", "?")] = by_verdict.get(e.get("verdict", "?"), 0) + 1
        ref = e.get("ref") or "direct"
        by_ref[ref] = by_ref.get(ref, 0) + 1
    return {"checks": checks, "by_verdict": by_verdict, "by_ref": by_ref}


router = APIRouter()


def _killed() -> JSONResponse | None:
    """Единый отказ, пока включён kill-switch: вердиктов и трат нет."""
    if not killswitch.is_active():
        return None
    return _error("kill_switch", "KARTA is stopped by the operator", 503,
                  "wait for the operator to resume")


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "karta-demo", "scenarios": len(SCENARIOS),
            "kill_switch": killswitch.status()}


@router.get("/api/v1/kill")
def kill_status() -> dict:
    return killswitch.status()


@router.post("/api/v1/kill")
async def kill_set(request: Request) -> JSONResponse:
    body = await request.json()
    state = killswitch.set_active(bool(body.get("active", True)), str(body.get("reason", "")))
    _record({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "scenario": "kill_switch", "verdict": "STOP" if state["active"] else "RESUME",
             "rule": "S3", "ref": request.query_params.get("ref", "api"), "evidence": ""})
    return JSONResponse(state)


@router.get("/metrics")
def metrics() -> dict:
    return _totals()


@router.get("/api/v1/evidence")
def evidence_bundle() -> JSONResponse:
    """Signed, offline-verifiable bundle of demo events (S3)."""
    records = evidence.load_jsonl(EVENTS) if EVENTS.exists() else []
    bundle = evidence.build_bundle(
        records,
        source="karta-demo",
        kill_switch=killswitch.status(),
    )
    bundle["evidence_id"] = hashlib.sha256(evidence.canonical(bundle)).hexdigest()[:16]
    evidence.save_evidence(bundle)
    return JSONResponse(bundle)


@router.get("/evidence/{evidence_id}", response_class=HTMLResponse)
def evidence_page(evidence_id: str):
    """Public, no-auth evidence viewer; the signature is verified in Python."""
    package = evidence.load_evidence(evidence_id)
    if package is None:
        return HTMLResponse("<h1>Evidence not found</h1>", status_code=404)
    if package.get("kind") == "event-bundle":
        valid = evidence.verify_bundle(package)["ok"]
    else:
        valid = evidence.verify_evidence(package)
    body = html.escape(json.dumps(package, ensure_ascii=False, indent=2))
    badge = "VALID" if valid else "INVALID"
    color = "#3fb950" if valid else "#f85149"
    chain = "valid" if package.get("chain_valid") else "not verified"
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KARTA evidence — {badge}</title>
<style>body{{background:#0b0d10;color:#e8e6e3;font:16px/1.6 system-ui,sans-serif;max-width:980px;margin:0 auto;padding:32px 20px}}
pre{{background:#11151a;border:1px solid #22272e;border-radius:10px;padding:16px;overflow:auto}}
b{{color:{color}}} code{{background:#171b21;padding:2px 5px;border-radius:4px}}.dim{{color:#8b949e}}</style>
</head><body>
<h1>KARTA evidence <b>{badge}</b></h1>
<p>Ed25519 signature: <b>{badge}</b> · Sakshi chain: <b>{chain}</b></p>
<p class="dim">Checked here without trusting the API. Repeat it with the public key in the JSON.</p>
<pre>{body}</pre>
<p class="dim">No wallet keys or secrets are included.</p>
</body></html>""", status_code=200)


@router.get("/api/scenarios")
def scenarios() -> list[dict]:
    return [
        {"id": sid, "title": s["title"], "note": s["note"],
         "budget": str(s["envelope"].budget_total),
         "per_call_max": str(s["envelope"].per_call_max),
         "calls_max": s["envelope"].calls_max,
         "allowlist": list(s["envelope"].allowlist)}
        for sid, s in SCENARIOS.items()
    ]


@router.post("/api/check")
async def check(request: Request) -> JSONResponse:
    stopped = _killed()
    if stopped is not None:
        return stopped
    body = await request.json()
    sid = str(body.get("scenario", ""))
    scenario = SCENARIOS.get(sid)
    if scenario is None:
        return JSONResponse({"error": {"code": "unknown_scenario",
                                       "suggested_action": "GET " + PREFIX + "/api/scenarios"}},
                            status_code=400)
    env: Envelope = scenario["envelope"]
    verdict = evaluate(env, scenario["request"])
    evidence = f"ev_{uuid.uuid4().hex[:16]}"
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario": sid, "verdict": verdict.verdict, "rule": verdict.rule,
        "ref": request.query_params.get("ref", ""), "evidence": evidence,
    }
    _record(payload)
    return JSONResponse({
        "envelope": {"id": env.envelope_id, "budget": str(env.budget_total),
                     "per_call_max": str(env.per_call_max), "calls_max": env.calls_max},
        "request": {"amount": str(scenario["request"].amount),
                    "payee": scenario["request"].payee,
                    "calls_so_far": scenario["request"].calls_so_far},
        "verdict": verdict.to_dict(),
        "evidence": evidence,
    })


# --- Публичный API конвертов (S2) -------------------------------------------
_CREATES: dict[str, list[float]] = {}
_CREATE_LIMIT = 10
_CREATE_WINDOW = 60.0


def _limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _CREATES.get(ip, []) if now - t < _CREATE_WINDOW]
    if len(hits) >= _CREATE_LIMIT:
        _CREATES[ip] = hits
        return True
    hits.append(now)
    _CREATES[ip] = hits
    return False


def _error(code: str, message: str, status: int, hint: str = "") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message,
                                   "retryable": status >= 500,
                                   "suggested_action": hint}}, status_code=status)


@router.post("/api/v1/envelopes")
async def create_envelope(request: Request) -> JSONResponse:
    stopped = _killed()
    if stopped is not None:
        return stopped
    ip = request.client.host if request.client else "?"
    if _limited(ip):
        return _error("rate_limited", "10 envelopes per minute", 429, "wait a minute")
    body = await request.json()
    try:
        envelope = ledger.create(
            budget_total=ledger.parse_decimal(body.get("budget_total"), "budget_total"),
            per_call_max=ledger.parse_decimal(body.get("per_call_max", "0"), "per_call_max"),
            calls_max=int(body.get("calls_max", 0)),
            allowlist=tuple(str(x).lower() for x in body.get("allowlist", [])),
            allow_new_payee=bool(body.get("allow_new_payee", False)),
            allow_subscriptions=bool(body.get("allow_subscriptions", False)),
            approval_threshold=(ledger.parse_decimal(body["approval_threshold"],
                                                     "approval_threshold")
                                if body.get("approval_threshold") is not None else None),
            ttl_hours=max(1, min(int(body.get("ttl_hours", 24)), 168)),
        )
    except (ValueError, TypeError) as exc:
        return _error("invalid_envelope", str(exc), 400, "POST /api/v1/envelopes")
    envelope["id"] = envelope["envelope_id"]  # алиас для коротких клиентов
    return JSONResponse(envelope, status_code=201)


@router.get("/api/v1/envelopes/{envelope_id}")
def read_envelope(envelope_id: str) -> JSONResponse:
    env = ledger.get(envelope_id)
    if env is None:
        return _error("not_found", "envelope not found", 404, "POST /api/v1/envelopes")
    return JSONResponse(env)


@router.post("/api/v1/envelopes/{envelope_id}/spend")
async def spend(envelope_id: str, request: Request) -> JSONResponse:
    stopped = _killed()
    if stopped is not None:
        return stopped
    body = await request.json()
    try:
        amount = ledger.parse_decimal(body.get("amount"), "amount")
    except ValueError as exc:
        return _error("invalid_request", str(exc), 400, "amount is decimal, e.g. 0.05")
    verdict, receipt = ledger.reserve(
        envelope_id, amount=amount, payee=str(body.get("payee", "")),
        is_subscription=bool(body.get("is_subscription", False)))
    state = ledger.get(envelope_id)
    if state is None:
        return _error("not_found", "envelope not found", 404, "POST /api/v1/envelopes")
    _record({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "scenario": "api_spend", "verdict": verdict.verdict, "rule": verdict.rule,
             "ref": request.query_params.get("ref", "api"),
             "evidence": (receipt or {}).get("receipt_id", "")})
    return JSONResponse({"verdict": verdict.to_dict(), "receipt": receipt, "envelope": state})


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KARTA — the policy decides, not the model</title>
<style>
:root{--bg:#0b0d10;--fg:#e8e6e3;--dim:#8b949e;--line:#22272e;--ok:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 -apple-system,Segoe UI,Inter,system-ui,sans-serif}
main{max-width:880px;margin:0 auto;padding:48px 24px 72px}
h1{font-size:34px;line-height:1.2;margin:0 0 8px;letter-spacing:-.02em}
.sub{color:var(--dim);margin:0 0 32px}
.grid{display:grid;gap:12px;margin:24px 0}
.card{border:1px solid var(--line);border-radius:12px;padding:16px 18px;cursor:pointer;
background:#11151a;transition:border-color .15s}
.card:hover{border-color:#3d444d}
.card b{display:block;margin-bottom:4px}
.card span{color:var(--dim);font-size:14px}
.out{border:1px solid var(--line);border-radius:12px;padding:20px;min-height:120px;background:#0f1318}
.v{font:600 26px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.02em}
.ALLOW{color:var(--ok)}.HOLD{color:var(--warn)}.BLOCK{color:var(--bad)}
dl{display:grid;grid-template-columns:160px 1fr;gap:6px 16px;margin:16px 0 0}
dt{color:var(--dim);font-size:14px}dd{margin:0;font-family:ui-monospace,Menlo,monospace;font-size:14px}
small{color:var(--dim)}a{color:#79c0ff}
</style></head><body><main>
<h1>The policy decides.<br>Not the model.</h1>
<p class="sub">KARTA — spend control for AI agents. One signed envelope per task, enforced
outside the model. Every check below is deterministic: same input, same rule, same verdict.
No wallet, no funds, no signup.</p>
<div class="grid" id="grid"></div>
<div class="out" id="out"><small>Pick a scenario. The envelope and the request are shown; the verdict is produced by the same engine the API and MCP use.</small></div>
<p style="margin-top:28px"><small>Free tier: 20 checks a day · <a href="https://rta.lat/nidhipati/">spend audit</a> · <a href="https://attest.rta.lat/">signed receipts</a></small></p>
</main><script>
const P=%PREFIX%;
async function run(id){
  const out=document.getElementById('out');
  out.innerHTML='<small>checking…</small>';
  const r=await fetch(P+'/api/check?ref=demo',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({scenario:id})});
  const d=await r.json();
  if(!d.verdict){out.textContent=JSON.stringify(d);return}
  const v=d.verdict;
  out.innerHTML=`<div class="v ${v.verdict}">${v.verdict}</div>
  <dl><dt>rule</dt><dd>${v.rule}</dd>
  <dt>reason</dt><dd>${v.reason}</dd>
  <dt>why</dt><dd>${v.counterfactual}</dd>
  <dt>next</dt><dd>${v.next}</dd>
  <dt>envelope</dt><dd>${d.envelope.id} · budget ${d.envelope.budget} · per-call ${d.envelope.per_call_max} · calls_max ${d.envelope.calls_max}</dd>
  <dt>request</dt><dd>${d.request.amount} → ${d.request.payee} · call #${d.request.calls_so_far+1}</dd>
  <dt>evidence</dt><dd>${d.evidence}</dd></dl>`;
}
fetch(P+'/api/scenarios').then(r=>r.json()).then(list=>{
  document.getElementById('grid').innerHTML=list.map(s=>
    `<div class="card" data-id="${s.id}"><b>${s.title}</b><span>${s.note}</span></div>`).join('');
  document.querySelectorAll('.card').forEach(c=>c.onclick=()=>run(c.dataset.id));
});
</script></body></html>"""


def create_app(prefix: str = PREFIX) -> FastAPI:
    from contextlib import asynccontextmanager
    from .spend_mcp import spend_mcp_dispatcher

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with spend_mcp_dispatcher.lifespan():
            yield

    ledger.init()
    app = FastAPI(title="KARTA demo", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(router, prefix=prefix)

    from starlette.routing import Route as _Route
    mount_path = f"{prefix}/mcp" if prefix else "/mcp"

    async def _mcp_forward(request: Request) -> Response:
        """Exact POST mount_path without a 307 redirect."""
        scope = dict(request.scope)
        scope["path"] = "/"
        messages: list[dict] = []

        async def _send(message: dict) -> None:
            messages.append(message)

        await spend_mcp_dispatcher(scope, request.receive, _send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        body = b"".join(
            m.get("body", b"") for m in messages if m["type"] == "http.response.body"
        )
        headers = {k.decode(): v.decode() for k, v in start.get("headers", [])}
        return Response(content=body, status_code=start["status"], headers=headers)

    app.router.routes.append(
        _Route(mount_path, endpoint=_mcp_forward,
               methods=["POST", "GET", "DELETE", "OPTIONS"])
    )
    app.mount(mount_path, spend_mcp_dispatcher)
    if prefix:  # поддомен обслуживает те же маршруты с корня
        app.include_router(router)

    @app.get(prefix or "/", response_class=HTMLResponse)
    def page() -> str:  # noqa: D401
        return PAGE.replace("%PREFIX%", prefix)

    if prefix:
        @app.get("/", response_class=HTMLResponse)
        def page_root() -> str:  # noqa: D401
            return PAGE.replace("%PREFIX%", "")

    @app.middleware("http")
    async def _timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-karta-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    return app


app = create_app()
