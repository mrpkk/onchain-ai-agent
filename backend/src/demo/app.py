"""Публичное демо KARTA «политика решает» (S1, SPEC v4 §8).

Одна страница, четыре сценария, ни одного реального платежа. Вердикт выдаёт
тот же evaluator, что используют API и MCP (`src/security/envelope.py`).
Метрики — свой JSONL, без внешней аналитики: считаем не «просмотры», а
дошедших до вердикта, с меткой канала `?ref=`.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

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


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "karta-demo", "scenarios": len(SCENARIOS)}


@router.get("/metrics")
def metrics() -> dict:
    return _totals()


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
    app = FastAPI(title="KARTA demo", docs_url=None, redoc_url=None)
    app.include_router(router, prefix=prefix)

    @app.get(prefix or "/", response_class=HTMLResponse)
    def page() -> str:  # noqa: D401
        return PAGE.replace("%PREFIX%", prefix)

    @app.middleware("http")
    async def _timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-karta-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    return app


app = create_app()
