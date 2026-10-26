"""Публичное демо KARTA «политика решает» (S1, SPEC v4 §8).

Одна страница, четыре сценария, ни одного реального платежа. Вердикт выдаёт
тот же evaluator, что используют API и MCP (`src/security/envelope.py`).
Метрики — свой JSONL, без внешней аналитики: считаем не «просмотры», а
дошедших до вердикта, с меткой канала `?ref=`.
"""

from __future__ import annotations

import hashlib
import html
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from ..security import evidence, killswitch, ledger, x402
from ..billing import usdc_invoice
from ..security.envelope import Envelope, SpendRequest, evaluate

PREFIX = os.getenv("KARTA_PREFIX", "").rstrip("/")
def events_path() -> Path:
    """Путь к журналу событий читается на каждом вызове: тесты подменяют его после импорта."""
    return Path(os.getenv("KARTA_DEMO_EVENTS",
                          str(Path.home() / ".local/share/karta-demo/events.jsonl")))
def pilots_path() -> Path:
    return Path(os.getenv("KARTA_PILOTS",
                          str(Path.home() / ".local/share/karta-demo/pilot-requests.jsonl")))


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
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _totals() -> dict:
    path = events_path()
    if not path.exists():
        return {"checks": 0, "by_verdict": {}, "by_ref": {}}
    by_verdict: dict[str, int] = {}
    by_ref: dict[str, int] = {}
    checks = 0
    for line in path.read_text(encoding="utf-8").splitlines():
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


_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")




def admin_token() -> str:
    """Токен владельца читается на каждом вызове: тесты и деплой задают его отдельно."""
    return os.getenv("KARTA_ADMIN_TOKEN", "").strip()


def _admin(request: Request) -> JSONResponse | None:
    expected = admin_token()
    if not expected:
        return _error("admin_disabled", "KARTA_ADMIN_TOKEN is not configured", 403,
                      "set KARTA_ADMIN_TOKEN in the service environment")
    if request.headers.get("x-admin-token", "") != expected:
        return _error("forbidden", "admin token required", 403, "send X-Admin-Token header")
    return None

@router.post("/api/v1/pilot-requests")
async def pilot_request(request: Request) -> JSONResponse:
    """Заявка на бесплатный пилот. Храним только то, что человек сам прислал."""
    stopped = _killed()
    if stopped is not None:
        return stopped
    ip = request.client.host if request.client else "?"
    if _limited(ip):
        return _error("rate_limited", "too many requests", 429, "try again later")
    body = await request.json()
    email = str(body.get("email", "")).strip()
    if not _EMAIL_RE.match(email):
        return _error("invalid_email", "a valid email is required", 400,
                      "send email like name@company.com")
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "id": "pilot_" + uuid.uuid4().hex[:12],
        "email": email,
        "name": str(body.get("name", "")).strip()[:120],
        "platform": str(body.get("platform", "")).strip()[:200],
        "scenario": str(body.get("scenario", "")).strip()[:500],
        "ref": request.query_params.get("ref", "direct")[:40],
        "ip_hash": hashlib.sha256(ip.encode()).hexdigest()[:16],
    }
    pilots_path().parent.mkdir(parents=True, exist_ok=True)
    with pilots_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _record({"ts": record["ts"], "scenario": "pilot_request", "verdict": "LEAD",
             "rule": "S7", "ref": record["ref"], "evidence": record["id"]})
    return JSONResponse({"id": record["id"], "status": "received"}, status_code=201)


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


@router.get("/api/v1/receipt/sample")
def sample_receipt() -> JSONResponse:
    """A real signed receipt for the /verify demo. Small budget, no money moves."""
    envelope = ledger.create(budget_total=Decimal("0.02"), per_call_max=Decimal("0.02"),
                             calls_max=1, allowlist=("api.example.com",), ttl_hours=1)
    _, receipt = ledger.reserve(envelope["envelope_id"], amount=Decimal("0.02"),
                                payee="api.example.com")
    return JSONResponse(receipt or {})


PRICING_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>KARTA — pricing</title>
<style>body{background:#0b0d10;color:#e8e6e3;font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:32px 20px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #22272e;padding:10px;text-align:left}
th{color:#8b949e}.price{color:#3fb950;font-weight:700}.dim{color:#8b949e}a{color:#7fd1b9}
.panel{background:#11151a;border:1px solid #22272e;border-radius:10px;padding:16px;margin:18px 0}</style>
</head><body>
<h1>KARTA pricing</h1>
<p class="dim">One price table. No per-call price as a business model. No custody, no token.</p>
<table><tr><th>Tier</th><th>Price</th><th>What</th></tr>
<tr><td>Open</td><td class="price">$0</td><td>MCP, 20 checks/day, demo, local run</td></tr>
<tr><td>Team</td><td class="price">$99/mo (India $49)</td><td>hosted control plane, 5,000 checks/mo, 5 envelopes, evidence export</td></tr>
<tr><td>Pilot</td><td class="price">$2,500 one-time</td><td>14 days: install, 3 policies, 1 integration, findings report, 30 days support</td></tr>
<tr><td>Enterprise</td><td class="price">from $25,000/year</td><td>white-label, SSO, private deployment, 5 checks in one entry, SLA</td></tr>
<tr><td>Retainer</td><td class="price">$1,500/mo</td><td>monthly reconciliation, new rules, incident review</td></tr></table>
<div class="panel"><b>Payment:</b> USDC invoice on Base, verified from chain logs; no card checkout is claimed.
Pilot starts after a written scope. <a href="mailto:maxim.pkk@gmail.com?subject=KARTA%20pilot">Request a pilot</a>.</div>
<p><a href="/karta">Demo</a> · <a href="/karta/enterprise">Enterprise pack</a> · <a href="/karta/verify">Verify a receipt</a></p>
</body></html>"""

ENTERPRISE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>KARTA — enterprise security pack</title>
<style>body{background:#0b0d10;color:#e8e6e3;font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:32px 20px}
h2{margin-top:28px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #22272e;padding:8px;text-align:left;vertical-align:top}
th{color:#8b949e}.dim{color:#8b949e}a{color:#7fd1b9}.badge{color:#3fb950;font-weight:700}</style>
</head><body>
<h1>KARTA enterprise pack</h1>
<p class="dim">12 questions a platform or issuer asks before a pilot. No SOC 2, ISO 27001, or regulatory approval is claimed.</p>
<table>
<tr><th>#</th><th>Question</th><th>Answer as built</th></tr>
<tr><td>1</td><td>Who owns keys?</td><td>Gateway, never the model; KeyVault/Fernet; no key in prompt, log or receipt.</td></tr>
<tr><td>2</td><td>Where is policy enforced?</td><td>Deterministic Dharma/envelope outside the model; rule id with every verdict.</td></tr>
<tr><td>3</td><td>Can the model override a block?</td><td>No; only a human approval surface can change the outcome.</td></tr>
<tr><td>4</td><td>What if the model is compromised?</td><td>Task envelope caps budget, per-call, calls, payees, subscriptions, expiry.</td></tr>
<tr><td>5</td><td>How do you stop an agent?</td><td>Operator kill switch; demo/API/MCP return 503; runtime hard kill; no auto-resume.</td></tr>
<tr><td>6</td><td>Where is the audit log?</td><td>Sakshi append-only HMAC chain; JSON/CSV export.</td></tr>
<tr><td>7</td><td>How can we verify without trusting you?</td><td>Ed25519 receipts and evidence; browser <a href="/karta/verify">/verify</a>; server can be offline.</td></tr>
<tr><td>8</td><td>What data leaves?</td><td>Demo metrics only; no keys or prompts. Hosted retention by DPA.</td></tr>
<tr><td>9</td><td>Blast radius of one task?</td><td>One envelope: budget, per-call, calls, allowlist, commitments, expiry.</td></tr>
<tr><td>10</td><td>Multi-tenant isolation?</td><td>API/MCP scoped to owner key; foreign agent ids 404; public demo stateless.</td></tr>
<tr><td>11</td><td>SLA?</td><td>Draft 99.5% monthly, 1-business-day response, 48h incident report; not measured; legal review.</td></tr>
<tr><td>12</td><td>Certifications?</td><td>None claimed; controls, logs, receipts and threat model for your review.</td></tr>
</table>
<h2>Deployment</h2><p>Public demo · hosted pilot · self-hosted Docker · embedded MCP/HTTP guard. No custody, no money transmission, no token.</p>
<h2>SLA / DPA</h2><p class="dim">Drafts only — <b>LEGAL REVIEW REQUIRED</b>. No credits, 99.99%, “bank-grade” or regulatory approval claims.</p>
<p><a href="mailto:maxim.pkk@gmail.com?subject=KARTA%20enterprise%20pilot">Request an enterprise pilot</a> · <a href="/karta/pricing">Pricing</a> · <a href="/karta">Demo</a></p>
</body></html>"""

VERIFY_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KARTA — verify a receipt offline</title>
<style>body{background:#0b0d10;color:#e8e6e3;font:16px/1.6 system-ui,sans-serif;max-width:900px;margin:0 auto;padding:32px 20px}
textarea{width:100%;min-height:260px;background:#11151a;color:#e8e6e3;border:1px solid #22272e;border-radius:10px;padding:14px;font:13px/1.5 ui-monospace,monospace}
button{background:#1c6b58;color:#eafff8;border:0;border-radius:8px;padding:12px 18px;font-weight:600;cursor:pointer}
pre{background:#11151a;border:1px solid #22272e;border-radius:10px;padding:14px;overflow:auto}.ok{color:#3fb950}.bad{color:#f85149}.dim{color:#8b949e}</style>
</head><body>
<h1>Verify a KARTA receipt</h1>
<p class="dim">Paste a receipt JSON. The Ed25519 signature is checked in this browser; the KARTA server is not called.</p>
<textarea id="in" placeholder="Paste receipt JSON here"></textarea>
<p><button id="go">Verify</button> <button id="sample" style="background:#30363d">Load signed sample</button></p>
<pre id="out">No receipt yet.</pre>
<script>
function canonical(v){if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
return JSON.stringify(v);}
function b64(s){const bin=atob(s);return Uint8Array.from(bin,c=>c.charCodeAt(0));}
async function verify(){
 const out=document.getElementById('out');
 try{
  const p=JSON.parse(document.getElementById('in').value);
  if(p.signed!==true){out.innerHTML='<span class="bad">INVALID</span> — signed is not true';return;}
  if(p.algorithm!=='Ed25519'){out.innerHTML='<span class="bad">INVALID</span> — algorithm is not Ed25519';return;}
  const {signature,public_key,algorithm,...body}=p;
  const key=await crypto.subtle.importKey('raw',b64(public_key),{name:'Ed25519'},false,['verify']);
  const ok=await crypto.subtle.verify('Ed25519',key,b64(signature),new TextEncoder().encode(canonical(body)));
  out.innerHTML=ok?'<span class="ok">VALID</span> — signature and payload match':'<span class="bad">INVALID</span> — signature does not match';
 }catch(e){out.innerHTML='<span class="bad">INVALID</span> — '+String(e).replace(/[<>&]/g,'');}
}
document.getElementById('go').onclick=verify;
document.getElementById('sample').onclick=async()=>{
 const r=await fetch('api/v1/receipt/sample');document.getElementById('in').value=JSON.stringify(await r.json(),null,2);verify();
};
</script>
</body></html>"""


@router.get("/verify", response_class=HTMLResponse)
def verify_page() -> str:
    return VERIFY_PAGE


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page() -> str:
    return PRICING_PAGE


@router.get("/invoice/{invoice_id}", response_class=HTMLResponse)
def invoice_page(invoice_id: str):
    """Public invoice page: amount, address, memo, status. No custody."""
    item = usdc_invoice.get(invoice_id)
    if item is None:
        return HTMLResponse("<h1>Invoice not found</h1>", status_code=404)
    status = item.get("status", "pending")
    color = "#3fb950" if status == "paid" else "#d29922"
    rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in item.items()
        if k not in {"payment_uri"}
    )
    pay = html.escape(item.get("payment_uri", ""))
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>KARTA invoice</title>
<style>body{{background:#0b0d10;color:#e8e6e3;font:16px/1.6 system-ui,sans-serif;max-width:820px;margin:0 auto;padding:32px 20px}}
table{{border-collapse:collapse;width:100%}}td{{border-bottom:1px solid #22272e;padding:8px;vertical-align:top}}
td:first-child{{color:#8b949e;width:180px}}code{{background:#171b21;padding:2px 5px;border-radius:4px}}
.status{{color:{color};font-weight:700}}input{{background:#11151a;color:#e8e6e3;border:1px solid #22272e;border-radius:8px;padding:10px;width:100%}}
button{{background:#1c6b58;color:#eafff8;border:0;border-radius:8px;padding:10px 16px;font-weight:600;margin-top:8px}}
pre{{background:#11151a;border:1px solid #22272e;border-radius:8px;padding:12px;overflow:auto}}</style>
</head><body>
<h1>KARTA invoice</h1>
<p>Status: <span class="status">{html.escape(status)}</span></p>
<table>{rows}</table>
<p class="dim">Pay USDC on Base to the address above, exact amount. The recipient is the address in this invoice; never a chat address.</p>
<p class="dim">Payment URI: <code>{pay}</code></p>
<h2>Already paid?</h2>
<p class="dim">Paste the Base transaction hash. The server reads the chain; if it cannot confirm, the invoice stays pending.</p>
<input id="tx" placeholder="0x…">
<button id="check">Check transaction</button>
<pre id="out"></pre>
<script>
document.getElementById('check').onclick=async()=>{{
 const tx=document.getElementById('tx').value.trim(); const out=document.getElementById('out');
 if(!tx){{out.textContent='Paste a transaction hash.';return;}}
 try{{
  const r=await fetch('api/v1/invoice/{invoice_id}/check',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{tx_hash:tx}})}});
  out.textContent=JSON.stringify(await r.json(),null,2);
 }}catch(e){{out.textContent=String(e);}}
}};
</script>
</body></html>""", status_code=200)


@router.post("/api/v1/invoice/{invoice_id}/check")
async def invoice_check(invoice_id: str, request: Request) -> JSONResponse:
    body = await request.json()
    try:
        item = usdc_invoice.verify(invoice_id, str(body.get("tx_hash", "")))
    except KeyError:
        return _error("not_found", "invoice not found", 404, "create an invoice first")
    return JSONResponse(item)


@router.get("/enterprise", response_class=HTMLResponse)
def enterprise_page() -> str:
    return ENTERPRISE_PAGE




@router.post("/api/v1/invoice")
async def create_invoice(request: Request) -> JSONResponse:
    """Выставить счёт (только владелец): без этого «первые деньги» не начать."""
    denied = _admin(request)
    if denied is not None:
        return denied
    body = await request.json()
    try:
        from ..billing import usdc_invoice as inv

        item = inv.create(body.get("amount"), memo=str(body.get("memo", ""))[:200],
                          ttl_hours=int(body.get("ttl_hours", 72)))
    except Exception as exc:  # noqa: BLE001 - контракт ошибки важнее типа
        return _error("invalid_invoice", str(exc)[:200], 400, "amount as string, e.g. \"2500\"")
    return JSONResponse(item, status_code=201)


@router.get("/api/v1/pilot-requests")
def pilot_requests(request: Request) -> JSONResponse:
    """Заявки на пилот (только владелец)."""
    denied = _admin(request)
    if denied is not None:
        return denied
    path = Path(os.getenv("KARTA_PILOTS",
                          str(Path.home() / ".local/share/karta-demo/pilot-requests.jsonl")))
    items = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                items.append(json.loads(line))
            except ValueError:
                continue
    return JSONResponse({"count": len(items), "items": items[-100:]})

@router.get("/api/v1/evidence")
def evidence_bundle() -> JSONResponse:
    """Signed, offline-verifiable bundle of demo events (S3)."""
    path = events_path()
    records = evidence.load_jsonl(path) if path.exists() else []
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


@router.post("/api/v1/x402/check")
async def x402_check(request: Request) -> JSONResponse:
    """S4: decide whether a 402 challenge is inside the task envelope.

    No network call, no payment. A real x402 client may execute only after
    this returns ALLOW; the demo never holds funds.
    """
    stopped = _killed()
    if stopped is not None:
        return stopped
    body = await request.json()
    envelope_id = str(body.get("envelope_id", ""))
    state = ledger.get(envelope_id)
    if state is None:
        return _error("not_found", "envelope not found", 404,
                      "POST /api/v1/envelopes")
    try:
        challenge = x402.parse_challenge(body.get("challenge") or {})
    except x402.ChallengeError as exc:
        return _error("invalid_challenge", str(exc), 400,
                      "send a valid x402 accepts[0] object")
    verdict, receipt = ledger.reserve(
        envelope_id, amount=challenge.amount, payee=challenge.payee,
        is_subscription=bool(body.get("is_subscription", False)))
    state = ledger.get(envelope_id)
    _record({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "scenario": "x402_guard", "verdict": verdict.verdict,
             "rule": verdict.rule, "ref": request.query_params.get("ref", "api"),
             "evidence": (receipt or {}).get("receipt_id", "")})
    return JSONResponse({
        "verdict": verdict.to_dict(),
        "challenge": {
            "scheme": challenge.scheme,
            "network": challenge.network,
            "asset": challenge.asset,
            "amount": str(challenge.amount),
            "payee": challenge.payee,
            "resource": challenge.resource,
        },
        "receipt": receipt,
        "envelope": state,
    })


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
<p style="margin-top:28px"><small>Free tier: 20 checks a day · <a href="https://rta.lat/nidhipati/">spend audit</a> · <a href="https://attest.rta.lat/">signed receipts</a> · <a href="mailto:hello@rta.lat?subject=KARTA%20pilot">run a 30-day pilot</a></small></p>
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
        app.router.routes.append(
            _Route("/mcp", endpoint=_mcp_forward,
                   methods=["POST", "GET", "DELETE", "OPTIONS"])
        )
        app.mount("/mcp", spend_mcp_dispatcher)

    LLMS = """# KARTA — spend control for AI agents

KARTA gives an agent one signed envelope per task: budget, allowed payees, no subscriptions,
expiry. The decision is made outside the model, so a prompt-injected agent cannot sign around it.
Every allowed spend returns an Ed25519 receipt that verifies offline.

## Endpoints (base https://karta.rta.lat)
- POST /api/v1/envelopes           {"budget_total":"2.50","per_call_max":"0.05","calls_max":2000,"allowlist":["api.example.com"],"ttl_hours":2}
- POST /api/v1/envelopes/{id}/spend {"amount":"0.05","payee":"api.example.com"}
- GET  /api/v1/envelopes/{id}      state: spent, remaining, calls_used
- POST /api/v1/envelopes/{id}/kill {"reason":"runaway loop"}
- GET  /api/v1/evidence/{id}       evidence bundle, offline-verifiable
- GET  /api/v1/evidence            event bundle with hash chain
- POST /api/v1/kill                {"active":true|false} operator stop for all verdicts
- POST /mcp                        MCP streamable HTTP (tools: check_spend, open_envelope)

## Rules (deterministic, rule ids are stable)
E01 envelope_expired · E02 subscription_not_permitted · E03 payee_not_allowed ·
E04 per_call_exceeded · E05 calls_exhausted · E06 budget_exceeded ·
E07 above_approval_threshold · E08 envelope_killed (reserved)

## Honest state
Pre-revenue. No paying customers. The invariant is proven by tests: 100 parallel spend requests
against a 50 x $0.05 budget produce exactly 50 approvals. Mainnet payment execution is disabled.

Pages: https://karta.rta.lat/attacks (three reproducible attacks), https://karta.rta.lat/pilot (30 days free)
Source: https://github.com/mrpkk/onchain-ai-agent (branch feature/v2-modernization)
Contact: hello@rta.lat
"""

    @app.get(f"{prefix}/attacks", response_class=HTMLResponse)
    def attacks_page() -> str:  # noqa: D401
        from .pages import ATTACKS_BODY, shell

        return shell("KARTA — three attacks, refused", ATTACKS_BODY)

    @app.get(f"{prefix}/pilot", response_class=HTMLResponse)
    def pilot_page() -> str:  # noqa: D401
        from .pages import PILOT_BODY, shell

        return shell("KARTA pilot — 30 days, free", PILOT_BODY)

    @app.get(f"{prefix}/report", response_class=HTMLResponse)
    def report_page() -> str:  # noqa: D401
        from .pages import REPORT_BODY, shell

        return shell("What agent tools say about money — registry survey", REPORT_BODY)

    @app.get(f"{prefix}/compare", response_class=HTMLResponse)
    def compare_page() -> str:  # noqa: D401
        from .pages import COMPARE_BODY, shell

        return shell("KARTA vs other agent spend guards", COMPARE_BODY)

    if prefix:  # поддомен обслуживает те же страницы с корня
        app.add_api_route("/report", report_page, response_class=HTMLResponse)
        app.add_api_route("/compare", compare_page, response_class=HTMLResponse)
        app.add_api_route("/attacks", attacks_page, response_class=HTMLResponse)
        app.add_api_route("/pilot", pilot_page, response_class=HTMLResponse)

    @app.get("/llms.txt", response_class=Response)
    def llms_txt() -> Response:
        return Response(content=LLMS, media_type="text/plain; charset=utf-8")

    @app.get("/sitemap.xml", response_class=Response)
    def sitemap() -> Response:
        body = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
                "<url><loc>https://karta.rta.lat/</loc></url>"
                "<url><loc>https://karta.rta.lat/llms.txt</loc></url>"
                "<url><loc>https://karta.rta.lat/attacks</loc></url>"
                "<url><loc>https://karta.rta.lat/pilot</loc></url>"
                "</urlset>")
        return Response(content=body, media_type="application/xml")

    @app.get("/robots.txt", response_class=Response)
    def robots_txt() -> Response:
        return Response(content="User-agent: *\nAllow: /\nSitemap: https://karta.rta.lat/sitemap.xml\n",
                        media_type="text/plain")

    @app.get("/.well-known/mcp-registry-auth", response_class=Response)
    def registry_auth() -> Response:
        # подтверждение владения доменом для официального реестра MCP
        return Response(content=os.getenv("MCP_REGISTRY_AUTH", ""),
                        media_type="text/plain")

    @app.get(prefix or "/", response_class=HTMLResponse)
    def page() -> str:  # noqa: D401
        return PAGE.replace("%PREFIX%", prefix)

    @app.get(f"{prefix}/partners", response_class=HTMLResponse)
    def partners_page() -> str:  # noqa: D401
        return PARTNERS_PAGE.replace("%PREFIX%", prefix)

    if prefix:
        @app.get("/", response_class=HTMLResponse)
        def page_root() -> str:  # noqa: D401
            return PAGE.replace("%PREFIX%", "")

        @app.get("/partners", response_class=HTMLResponse)
        def partners_root() -> str:  # noqa: D401
            return PARTNERS_PAGE.replace("%PREFIX%", "")

    @app.middleware("http")
    async def _timing(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-karta-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    return app


app = create_app()


PARTNERS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KARTA design partners — free pilot</title>
<style>
:root{--bg:#0b0d10;--fg:#e8e6e3;--dim:#8b949e;--line:#22272e;--ok:#3fb950}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 -apple-system,Segoe UI,Inter,system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:48px 24px 72px}
h1{font-size:32px;line-height:1.2;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:18px;margin:28px 0 8px}
.sub{color:var(--dim);margin:0 0 24px}
ul{padding-left:20px}li{margin:6px 0}
form{border:1px solid var(--line);border-radius:12px;padding:20px;background:#0f1318;margin:24px 0}
label{display:block;font-size:14px;color:var(--dim);margin:12px 0 4px}
input,textarea{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;
background:#0b0d10;color:var(--fg);font:inherit}
button{margin-top:16px;padding:11px 18px;border:0;border-radius:8px;background:var(--ok);
color:#04140a;font-weight:600;font-size:15px;cursor:pointer}
small{color:var(--dim)}a{color:#79c0ff}
.ok{border:1px solid var(--ok);border-radius:10px;padding:14px 16px;margin:16px 0;display:none}
</style></head><body><main>
<h1>Free 30-day design partner pilot</h1>
<p class="sub">KARTA puts a signed task envelope around an AI agent's spending, enforced
outside the model. We are looking for five teams that let an agent pay for APIs,
data or other agents — and want a hard stop before it overspends.</p>

<h2>What you get</h2>
<ul>
<li>a review of one real spend flow in your agent (calls, limits, payees);</li>
<li>an envelope configuration you can apply the same day;</li>
<li>a sample evidence package: every decision, stop and resume, verifiable offline;</li>
<li>direct line to the maintainer for 30 days. No fee, no card.</li>
</ul>

<h2>What we ask</h2>
<ul>
<li>one call (30 min) about how your agent spends today;</li>
<li>permission to name you as a design partner <b>only after</b> you deploy it;</li>
<li>a short honest quote if it actually helped.</li>
</ul>

<form id="f">
<label for="email">Work email *</label>
<input id="email" type="email" required placeholder="name@company.com">
<label for="name">Your name</label>
<input id="name" placeholder="Ada">
<label for="platform">Agent or platform</label>
<input id="platform" placeholder="what your agent does, and what it pays for">
<label for="scenario">One spend that worries you</label>
<textarea id="scenario" rows="3" placeholder="e.g. our agent buys market data per call and once ran 40k calls in a night"></textarea>
<button type="submit">Request the pilot</button>
<small>We store your email and text locally and use it only to reply. No third-party analytics.</small>
</form>
<div class="ok" id="ok">Received. We reply within two business days.</div>
<p><small>Prefer to look first? <a href="%PREFIX%/verify">Check any envelope</a> or
<a href="%PREFIX%/../">try the live demo</a>.</small></p>
<script>
const f=document.getElementById('f');
f.addEventListener('submit',async(e)=>{e.preventDefault();
const body={email:email.value,name:name.value,platform:platform.value,scenario:scenario.value};
const r=await fetch('%PREFIX%/api/v1/pilot-requests',{method:'POST',
headers:{'content-type':'application/json'},body:JSON.stringify(body)});
if(r.ok){f.style.display='none';document.getElementById('ok').style.display='block';}
else{const j=await r.json().catch(()=>({}));alert((j.error&&j.error.message)||'could not send');}});
</script>
</main></body></html>"""
