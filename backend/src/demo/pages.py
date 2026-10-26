"""Статические страницы KARTA: /attacks и /pilot.

Отдельный модуль, чтобы не трогать логику API и не ломать демо. Тексты совпадают с
`docs/POST-ATTACKS.md` и `docs/PILOT.md`: один источник смысла, две формы подачи.
"""

from __future__ import annotations

SHELL_CSS = """body{margin:0;background:#0b0d10;color:#e8e6e3;font:16px/1.65 -apple-system,Segoe UI,Inter,system-ui,sans-serif}
main{max-width:820px;margin:0 auto;padding:48px 22px 80px}h1{font-size:32px;line-height:1.2;margin:0 0 10px}
h2{font-size:20px;margin:32px 0 8px}p{color:#c8c6c3}small,.dim{color:#8b949e}
code,pre{font-family:ui-monospace,Menlo,monospace;font-size:13.5px}
pre{background:#0f1318;border:1px solid #22272e;border-radius:10px;padding:14px;overflow:auto}
table{width:100%;border-collapse:collapse;margin:14px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #22272e;font-size:14.5px}
th{color:#8b949e;font-weight:500}a{color:#79c0ff}
.cta{display:inline-block;margin:24px 8px 0 0;border:1px solid #3d444d;border-radius:10px;padding:10px 16px;text-decoration:none;color:#e8e6e3}
.cta:hover{border-color:#79c0ff}"""


def shell(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{SHELL_CSS}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


ATTACKS_BODY = """
<h1>Three ways an agent with a wallet loses money</h1>
<p class="dim">Reproducible in ten minutes. Each script exits 0 when the attack is refused.</p>

<h2>1. The loop that is always right</h2>
<p>A pagination bug made an agent request the same paid pages. 41 000 calls, every one correctly
signed and settled. A per-call limit never notices: each call was legal.</p>
<pre>python3 attacks/runaway_loop.py
allowed: 2000  blocked: 39000  spent: 100.00  remaining: 0.00</pre>

<h2>2. The vendor nobody approved</h2>
<p>A scraped page says the dataset is available from an unknown vendor. The agent buys it.</p>
<pre>python3 attacks/prompt_injection_payee.py
verdict: BLOCK  rule: E03  reason: payee_not_allowed</pre>

<h2>3. The tool that inflates the price</h2>
<p>A trusted tool returns 1000x the real amount. The model passes it through.</p>
<pre>python3 attacks/tool_poisoning_amount.py
verdict: BLOCK  rule: E04  reason: per_call_exceeded</pre>

<h2>What stops it</h2>
<table><tr><th>Rule</th><th>Meaning</th></tr>
<tr><td>E02</td><td>subscriptions are not permitted by the envelope</td></tr>
<tr><td>E03</td><td>payee is not in the allowlist</td></tr>
<tr><td>E04</td><td>amount exceeds the per-call limit</td></tr>
<tr><td>E05</td><td>the task has used all its calls</td></tr>
<tr><td>E06</td><td>the task budget would be exceeded</td></tr></table>

<h2>What this does not prove</h2>
<p>No funds move here: this is the decision layer, not the settlement rail. Mainnet payment
execution is disabled by default. What is proven is the invariant — 100 parallel spend requests
against a 50 x $0.05 budget produce exactly 50 approvals.</p>

<a class="cta" href="/pilot">Run a 30-day pilot</a>
<a class="cta" href="https://github.com/mrpkk/onchain-ai-agent/tree/feature/v2-modernization/attacks">Source</a>
"""


PILOT_BODY = """
<h1>Pilot: 30 days, free</h1>
<p class="dim">For teams whose agents pay for things. One workflow, real numbers, one honest review.</p>

<h2>What you get</h2>
<table><tr><th>Day</th><th>Deliverable</th></tr>
<tr><td>1-2</td><td>one task envelope for one real workflow: budget, allowed payees, no subscriptions, expiry</td></tr>
<tr><td>3-5</td><td>the guard in front of your paid calls: ALLOW / HOLD / BLOCK with rule id and reason</td></tr>
<tr><td>6-10</td><td>kill switch drilled on a staging agent (stop under 2 s), evidence pack produced</td></tr>
<tr><td>11-20</td><td>two more envelopes; the numbers: blocked payments, prevented spend, false blocks</td></tr>
<tr><td>21-30</td><td>written review: what held, what broke, what you would need before paying</td></tr></table>

<h2>What it costs</h2>
<p>Nothing for 30 days. No revenue share, no lock-in, no logo requirement.
After the pilot: Team $99/month (India $49) or Enterprise from $25 000/year for white-label.</p>

<h2>What we ask</h2>
<p>One honest paragraph about where it broke. Permission to name you only if you actually installed
it. One introduction if you think it is worth another team's time.</p>

<h2>What we do not claim</h2>
<p>No "100 % safety": the policy is only as good as the envelope you write. We do not hold funds.
There are no paying customers yet — the pilot exists to find out whether this is worth paying for,
and the review will say what we learned.</p>

<h2>Refund rule</h2>
<p>If a paid pilot does not get its first live envelope within five business days, you get 100 %
back in USDC. No forms, no discussion.</p>

<a class="cta" href="mailto:hello@rta.lat?subject=KARTA%20pilot">Start a pilot</a>
<a class="cta" href="/">See the demo</a>
"""


COMPARE_BODY = """
<h1>How KARTA differs from other agent spend guards</h1>
<p class="dim">Every claim about another product below is quoted from its own one-line description in
the awesome-mcp-servers list (26.10.2026). Where a feature is not mentioned, the cell says
"not stated" — that is not a claim that it is missing.</p>

<table>
<tr><th>Product</th><th>What it says about itself</th></tr>
<tr><td><b>KARTA</b></td><td>Signed budget envelope <b>per task</b>, enforced outside the model,
kill switch under two seconds, Ed25519 receipt verified offline. 406 tests, live demo.</td></tr>
<tr><td>spendshield</td><td>"Payment guardrails for AI agents: spend caps, budget and approval gates,
prompt-injection defense, an encrypted secret vault and an audit trail."</td></tr>
<tr><td>agentic-wallet-guardian</td><td>"Evaluates AI agents' proposed blockchain transactions and
returns an explainable allow, warn or block decision."</td></tr>
<tr><td>toolwrit</td><td>"Deny-by-default tool allowlist with argument rules, call and USD budget caps,
and a hash-chained audit log with RFC 3161 timestamp anchors."</td></tr>
<tr><td>DashClaw</td><td>"Fail-closed approval layer for unattended agent runs: checks actions against
org policy, requests human approval and logs every decision to a causal ledger."</td></tr>
</table>

<h2>Where the difference actually is</h2>
<table>
<tr><th>Capability</th><th>KARTA</th><th>Others (as described)</th></tr>
<tr><td>Budget belongs to the <b>task</b>, not the call</td><td>yes</td>
<td>spendshield: caps; toolwrit: call and USD caps; a pagination loop is not covered by a per-call cap</td></tr>
<tr><td>Enforcement outside the model (agent cannot sign around it)</td><td>yes</td>
<td>DashClaw: approval layer; others: not stated how the agent is prevented from bypassing</td></tr>
<tr><td>Kill switch for one agent, under 2 s</td><td>yes, measured</td><td>not stated</td></tr>
<tr><td>Receipt verified <b>offline</b> by a third party</td><td>yes, Ed25519</td>
<td>toolwrit: hash-chained log with RFC 3161; others: audit trail, not third-party verification</td></tr>
<tr><td>Cross-rail view (x402 + on-chain + card token)</td><td>yes, by design</td><td>not stated</td></tr>
<tr><td>Open source you can run in ten minutes</td><td>yes</td><td>not stated</td></tr>
</table>

<h2>What this page is not</h2>
<p>It is not a claim that those products are worse. They are solving adjacent problems, and several
are further along commercially than we are: KARTA has no paying customers. If you need a spend cap
today, toolwrit or spendshield may be exactly right. If you need to prove to an auditor that a
payment was inside the task budget, that is the gap we fill.</p>

<a class="cta" href="/pilot">Run a 30-day pilot</a>
<a class="cta" href="/attacks">See the three attacks</a>
"""
