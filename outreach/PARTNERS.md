# KARTA — design partners and platform outreach

**Status 26.10.2026:** 0 partners, 0 emails sent. This is a prepared pack, not a claim.
**STOP-GATE G3:** sending requires the owner's explicit permission. Do not send from an agent.

---

## One-liner

**KARTA is the spend-control layer between an AI agent and its wallet:** a signed task envelope,
enforcement outside the model, a kill switch, and a receipt an auditor can verify offline.

Live: <https://rta.lat/karta> · MCP: `https://rta.lat/karta/mcp` · verify: `/karta/verify`

---

## 5 platform targets (white-label / integration)

| Target | Why | Public entry | Status |
|---|---|---|---|
| **Glama** | MCP directory; KARTA can be a listed guard | https://glama.ai/mcp/connectors | not contacted |
| **Smithery** | MCP hosting/distribution; shutting down 31.10 — verify first | https://smithery.ai | not contacted; channel closing |
| **Coinbase Developer Platform** | x402/AgentKit wallets need a pre-spend policy | https://www.coinbase.com/developer-platform | not contacted |
| **Circle** | USDC agent payments; reserve/treasury angle | https://www.circle.com | not contacted |
| **Virtuals / Olas** | agent platforms with wallets and budgets | https://virtuals.io · https://olas.network | not contacted |

**What to offer:** white-label `check_spend` + envelope API; no custody; 14-day pilot; revenue share
or enterprise licence. **Do not** claim a partnership before signature.

---

## 5 design-partner targets (free pilot)

| Target | Public signal | Contact | Status |
|---|---|---|---|
| **BlockRunAI / Franklin** | agent with a wallet; public repo | `hello@blockrun.ai` (public SECURITY.md) | not contacted |
| **Agent402** | 500+ pay-per-call tools over x402 | `mike@agent402.tools` (public README) | not contacted |
| **GetBindu / Bindu** | identity + payments layer for agents | GitHub issue #615 | previously cold, 0 response |
| **Daydreams** | agents for commerce | GitHub issue #708 | previously cold, 0 response |
| **OneShot** | tools/payments/compute for agents | GitHub issue #7 | previously cold, 0 response |

**Rule:** the three previously cold targets are **not** re-contacted without a new, specific reason.
Start with Franklin and Agent402 only if the owner approves G3.

---

## Email 1 — design partner (short, one finding)

Subject: `KARTA: a spend envelope for {project}'s agent wallet`

> Hi {name},
>
> {project} gives an agent a wallet. The missing piece I keep seeing is the task budget: a per-call
> limit does not stop a pagination bug from making 41,000 correct payments.
>
> KARTA wraps one task in a signed envelope: total budget, per-call max, calls max, payee allowlist,
> subscription policy, expiry. The model asks; the gateway decides; a receipt verifies offline.
>
> I can run a free 14-day pilot: 3 policies on one agent, no custody, no keys. If it does not catch
> a real overspend, we say so and stop.
>
> Is the wallet spend controlled by the agent, or by a policy service today?

**No links in the first email** (deliverability); attach nothing.

---

## Email 2 — platform (white-label)

Subject: `Pre-spend policy for your agent wallets`

> Hi {name},
>
> Your users run agents with budgets. The rails verify that a payment happened; nobody answers
> whether this agent should spend this money on this task.
>
> KARTA adds that layer: signed task envelope, deterministic ALLOW/HOLD/BLOCK with a rule id,
> kill switch in under 2 seconds, and an Ed25519 evidence package an auditor verifies offline.
>
> We can pilot as a white-label guard inside {platform}: one endpoint, no custody, no token.
> Would a 20-minute written security review be useful? I can send the 12-question pack.

---

## Email 3 — RWA / treasury (enterprise)

Subject: `Private reserve attestation without publishing the portfolio`

> Hi {name},
>
> {issuer} publishes a reserve/NAV claim. A buyer cannot verify it without trusting the dashboard,
> and a full disclosure exposes positions.
>
> KARTA produces a signed reserve attestation: every line has a source hash, missing prices fail
> closed, and the buyer verifies offline. A ZK predicate can prove “reserves ≥ liabilities” without
> revealing the amount.
>
> Productized single-asset report from $5,000; issuer/white-label from $50,000.
> Who signs off on the reserve methodology today?

---

## Tracker

`outreach/PARTNERS.csv` — one row per target, `status=not_contacted` until a reply.

**Metrics:** 10 targets verified, 5 emails approved, 2 replies, 1 pilot. No fake partner names.
