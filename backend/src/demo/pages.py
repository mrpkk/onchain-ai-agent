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
.cta:hover{border-color:#79c0ff}
@media print{body{background:#fff;color:#111}main{max-width:none;padding:0}
h1{font-size:24px}h2{font-size:15px;margin:18px 0 6px;break-after:avoid}
p,td,th{font-size:11.5px;color:#111}table{break-inside:avoid}
pre{background:#f5f5f5;border-color:#ddd;color:#111}
a{color:#111;text-decoration:none}.cta,.dim{display:none}}"""


def shell(title: str, body: str, *, description: str = "", path: str = "/",
          lang: str = "en") -> str:
    """Одна оболочка для страниц: заголовок, описание, OG-карточка и JSON-LD.

    Без этого ссылка в письме разворачивается в голый URL — а письма мы шлём именно ссылкой.
    """
    desc = description or ("KARTA — spend control for AI agents: a signed budget envelope per task, "
                           "a kill switch, and receipts verified offline.")
    url = "https://karta.rta.lat" + path
    og = (
        f'<meta name="description" content="{desc}">'
        f'<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{desc}">'
        f'<meta property="og:url" content="{url}">'
        f'<meta property="og:site_name" content="KARTA">'
        f'<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{title}">'
        f'<meta name="twitter:description" content="{desc}">'
        '<meta property="og:image" content="https://karta.rta.lat/og.png">'
        '<meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="630">'
        '<meta name="twitter:image" content="https://karta.rta.lat/og.png">'
    )
    ld = (
        '{"@context":"https://schema.org","@type":"SoftwareApplication",'
        '"name":"KARTA","applicationCategory":"SecurityApplication",'
        '"operatingSystem":"Any","url":"https://karta.rta.lat",'
        '"description":"Spend control for AI agents: signed budget envelope per task, '
        'kill switch, Ed25519 receipts verified offline.",'
        '"offers":{"@type":"Offer","price":"0","priceCurrency":"USD"}}'
    )
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>{og}"
        f'<script type="application/ld+json">{ld}</script>'
        f"<style>{SHELL_CSS}</style></head>"
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
<p class="dim">For teams whose agents pay for things. One workflow, real numbers, one honest review.<br>Independently evaluated: <b>Glama rated A</b> (Healthy, 6 MCP tools, 27.10.2026).</p>

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


REPORT_BODY = """
<h1>What agent tools say about money</h1>
<p class="dim">A survey of the official MCP registry, 26.10.2026. Reproducible from the repository.</p>

<p>We read the public description of the first 2 500 servers in the registry and separated the ones
that describe a payment, wallet or x402 function.</p>

<table>
<tr><th>Measure</th><th>Count</th></tr>
<tr><td>Servers in the sample</td><td>2 500</td></tr>
<tr><td>Describe a payment, wallet or x402 function</td><td><b>72</b></td></tr>
<tr><td>…mention a budget</td><td>11</td></tr>
<tr><td>…mention a limit or a cap</td><td>0</td></tr>
<tr><td>…mention a kill switch or emergency stop</td><td><b>0</b></td></tr>
<tr><td>…describe a per-task budget</td><td><b>0</b></td></tr>
<tr><td>…mention a receipt</td><td>2</td></tr>
<tr><td>…mention an audit trail</td><td>0</td></tr>
</table>

<p>The 2 500 descriptions mention "approval" 65 times and "audit" 26 times overall — but almost none
of those are in the payment group. The tools that move money describe what they pay for, not what
stops them.</p>

<h2>Honest limits</h2>
<p><b>Descriptions are marketing text.</b> Absence of the word "kill switch" does not prove absence of
the feature — it proves the vendor does not consider it worth a line, which is itself a signal.
The sample is 2 500 of a larger, changing registry; the filter is lexical; we did not call the
servers, we read what they publish.</p>

<h2>Why publish it</h2>
<p>Because the number is checkable. Nine lines of Python over a public API, snapshot date included in
the repository — anyone can re-run it and get their own count. If your tool does have limits, write
them in the description: buyers cannot see what is not written.</p>

<a class="cta" href="/pilot">Run a 30-day pilot</a>
<a class="cta" href="/compare">Compare with other guards</a>
"""


PILOT_HI_BODY = """
<h1>पायलट: 30 दिन, निःशुल्क</h1>
<p class="dim">उन टीमों के लिए जिनके AI एजेंट पैसे खर्च करते हैं। एक वर्कफ़्लो, वास्तविक संख्याएँ,
और एक ईमानदार समीक्षा।</p>

<h2>आपको क्या मिलेगा</h2>
<table>
<tr><th>दिन</th><th>क्या</th></tr>
<tr><td>1-2</td><td>एक वर्कफ़्लो के लिए एक हस्ताक्षरित बजट लिफ़ाफ़ा: राशि, अनुमत भुगतान-प्राप्तकर्ता,
कोई सब्सक्रिप्शन नहीं, समाप्ति तिथि</td></tr>
<tr><td>3-5</td><td>आपके भुगतान वाले कॉल के आगे गार्ड: ALLOW / HOLD / BLOCK और नियम संख्या</td></tr>
<tr><td>6-10</td><td>स्टेजिंग एजेंट पर किल-स्विच का अभ्यास (दो सेकंड से कम), साक्ष्य-पैकेज तैयार</td></tr>
<tr><td>11-20</td><td>दो और लिफ़ाफ़े; संख्याएँ: रोके गए भुगतान, बचाया गया खर्च, गलत ब्लॉक</td></tr>
<tr><td>21-30</td><td>लिखित समीक्षा: क्या टिका, क्या टूटा, भुगतान से पहले क्या चाहिए</td></tr>
</table>

<h2>लागत</h2>
<p>30 दिन तक कुछ नहीं। कोई राजस्व-हिस्सा नहीं, कोई लॉक-इन नहीं। पायलट के बाद:
टीम <b>$99/माह</b> (भारत <b>$49</b>) या एंटरप्राइज़ <b>$25 000/वर्ष</b> से।</p>

<h2>हम क्या माँगते हैं</h2>
<p>एक ईमानदार अनुच्छेद: कहाँ टूटा। नाम का उपयोग केवल तब, जब आपने वास्तव में इंस्टॉल किया हो।
और एक परिचय, अगर आपको लगे कि किसी और टीम के लिए यह उपयोगी है।</p>

<h2>हम क्या दावा नहीं करते</h2>
<p>«100 % सुरक्षा» नहीं। हम पैसा नहीं रखते। अभी कोई भुगतान करने वाला ग्राहक नहीं है —
पायलट यह पता लगाने के लिए है कि यह भुगतान के योग्य है या नहीं, और समीक्षा में वही लिखा जाएगा
जो हमने सीखा।</p>

<h2>वापसी का नियम</h2>
<p>यदि भुगतान किए गए पायलट में पाँच कार्य-दिवसों के भीतर पहला लाइव लिफ़ाफ़ा नहीं बना,
तो पूरा 100 % USDC में वापस। कोई फ़ॉर्म नहीं, कोई बहस नहीं।</p>

<a class="cta" href="mailto:hello@rta.lat?subject=KARTA%20pilot%20(India)">पायलट शुरू करें</a>
<a class="cta" href="/">डेमो देखें</a>
"""


DECK_BODY = """
<h1>KARTA — spend control for AI agents</h1>
<p class="dim">A one-page deck for a licence conversation. Every number here is checkable.</p>

<h2>1. The problem</h2>
<p>Agents now hold wallets and pay per call. The rails are solved: x402 went to the Linux Foundation,
AP2 to the FIDO Alliance, UCP and ACP cover checkout, EMVCo published a draft. Every one of them
answers <i>can this payment be verified</i>. None answers <i>should this agent spend this money on
this task, now</i>.</p>

<h2>2. The evidence</h2>
<table>
<tr><th>Fact</th><th>Number</th></tr>
<tr><td>Agent paid calls in one weekend from a pagination bug, every payment valid</td><td>41 000</td></tr>
<tr><td>Hidden text changed an AP2 agent's cart in tests</td><td>56 %</td></tr>
<tr><td>Vendors documenting a kill switch (of 47 checked)</td><td>11</td></tr>
<tr><td>MCP registry servers that move money (of 2 500)</td><td>72</td></tr>
<tr><td>…of those, mentioning a kill switch or a per-task budget</td><td><b>0</b></td></tr>
</table>
<p class="dim">Source: our registry survey, 26.10.2026 — reproducible with one script in the repository.</p>

<h2>3. What we built</h2>
<p>One signed envelope per task: budget, allowlisted payees, no subscriptions, expiry, owner, cost
centre. The decision is made outside the model — the gateway holds the key, the agent only asks.
A kill switch stops one agent in under two seconds. Every spend returns an Ed25519 receipt a third
party verifies offline.</p>

<h2>4. Proof, not slides</h2>
<table>
<tr><th>Invariant</th><th>Result</th></tr>
<tr><td>100 parallel spends against a 50 × $0.05 budget</td><td>exactly 50 approved</td></tr>
<tr><td>1 000 calls at $0.01 against a $5 budget</td><td>exactly 500 approved</td></tr>
<tr><td>Injected payee, poisoned tool, runaway loop</td><td>all refused, reproducible in minutes</td></tr>
<tr><td>Automated tests</td><td>413 passing</td></tr>
<tr><td>External evaluation</td><td>Glama: <b>rated A</b>, Healthy, 6 tools (27.10.2026)</td></tr>
</table>

<h2>5. The market</h2>
<p>Every rail is adding budgets one at a time: AWS AgentCore Payments has session caps, Cloudflare
Wallets has allowances, Stripe and Ramp issue per-agent cards. Each limits its own rail and none
knows what the others already spent on the same task. The cross-rail task envelope is the missing
object.</p>

<h2>6. Who buys</h2>
<p>Agent platforms (white-label guard), crypto protocols with a treasury (policy + evidence),
teams whose agents pay for data and APIs (pilot, then Team plan).</p>

<h2>7. Business model</h2>
<table>
<tr><th>Tier</th><th>Price</th></tr>
<tr><td>Open</td><td>$0 — 20 checks/day, MCP, self-host</td></tr>
<tr><td>Team</td><td>$99/month ($49 India)</td></tr>
<tr><td>Pilot</td><td>$2 500 — 30 days, written review</td></tr>
<tr><td>Enterprise</td><td>from $25 000/year, white-label</td></tr>
<tr><td>Perpetual licence / asset purchase</td><td>$50 000–150 000 / $150 000–1 000 000</td></tr>
</table>

<h2>8. Traction — honestly</h2>
<p>Pre-revenue. No paying customers. 33 personalised letters to platforms, wallet providers and
payment sellers, zero replies at the time of writing. Six distribution channels (official MCP
registry, Docker catalogue entry, mcpservers.org, mcp.directory, awesome-mcp-servers PR, Glama
pending). What exists is working software, reproducible tests and a live demo — not revenue.</p>

<h2>9. Why it is defensible</h2>
<p>Not the policy file — the evidence chain: mandate → action → spend → receipt, cross-rail,
verifiable by someone who trusts neither party. That chain is running and tested; a buyer starting
today needs three to six months to reach parity.</p>

<h2>10. The ask</h2>
<p>One of three: a 30-day pilot for one team ($0), a licence conversation with whoever owns agent
payments at your company, or one introduction to a team whose agents already pay.</p>

<a class="cta" href="/deck.pdf">Download as PDF</a>
<a class="cta" href="mailto:hello@rta.lat?subject=KARTA%20deck">Write to us</a>
<a class="cta" href="/report">See the survey</a>
<a class="cta" href="/attacks">Run the attacks</a>
"""


OFFER_BODY = """
<h1>What you can buy, and what it costs</h1>
<p class="dim">Written offer. Payment in <b>USDC only</b>. No subscription traps: every line has a scope,
a price and a refund rule.</p>

<table>
<tr><th>Item</th><th>Price</th><th>What you get</th></tr>
<tr><td><b>Spend audit</b></td><td><b>$500</b>, 5 business days</td>
<td>One month of your agent logs: duplicates, failed-but-billed, quote-vs-settled, missing refunds.
Report with exact leaks and fix order; if it finds nothing, it says so.</td></tr>
<tr><td><b>KARTA pilot</b></td><td><b>$2 500</b>, 30 days</td>
<td>One workflow: signed task envelope, guard in front of paid calls, kill-switch drill, evidence pack,
written review with numbers. Refund 100 % if the first envelope is not live in 5 business days.</td></tr>
<tr><td><b>Reserve attestation</b></td><td><b>$2 500</b>, 30 days</td>
<td>One asset: Ed25519-signed attestation over a reserve snapshot, source hashes, methodology, retest.
The verifier stays with you.</td></tr>
<tr><td><b>attest</b> subscription</td><td><b>$99/month</b></td>
<td>Artifact verification: schema, emptiness, provenance, authority. Cancel anytime.</td></tr>
<tr><td><b>KARTA</b> subscription</td><td><b>$299/month</b></td>
<td>Hosted control plane: envelopes, kill switch, receipts, evidence export.</td></tr>
</table>

<h2>How to pay</h2>
<p><b>USDC on Base</b> (chain id 8453), exact amount, one invoice per item:<br>
<code id="addr">0xefCD6886f73064ea9EcbaA4741Ef1309A0885C59</code>
<button type="button" onclick="navigator.clipboard.writeText(document.getElementById('addr').innerText)">Copy address</button></p>
<p class="dim">Verify first 6 and last 4 characters against this page before sending. The address is never
sent in chat. Network: Base only; other networks by written agreement.</p>
<p><b>Crypto only.</b> No cards, no YooMoney, no bank transfer — we invoice in USDC and nothing else.
If your finance team needs a different rail, say so before ordering and we will tell you honestly that
we cannot take it yet.</p>

<h2>What happens after payment</h2>
<p>Within 24 hours: transaction confirmed on Basescan (or card receipt), kickoff scheduled, scope frozen
in writing. Deliverables are listed in the invoice; nothing is "best effort".</p>

<h2>Refund</h2>
<p>Audit: full refund if the report is not delivered in 5 business days. Pilot and attestation: full refund
if the first deliverable is not live in 5 business days. After that the work is done and the payment is final.</p>

<h2>What we do not do</h2>
<p>No token, no custody, no money transmission. No "100 % safety". No promises about token price or returns.
No named customers until they agree in writing.</p>

<a class="cta" href="mailto:hello@rta.lat?subject=KARTA%20order">Order by email</a>
<a class="cta" href="/pilot">Pilot details</a>
<a class="cta" href="/report">The survey behind this</a>
"""
