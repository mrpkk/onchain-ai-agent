# KARTA — one page for a licence conversation

**What it is.** The spend-control layer for AI agents that pay. One signed envelope per task
(budget, allowed payees, no subscriptions, expiry), the decision made **outside the model**, a
kill switch that stops one agent in under two seconds, and an Ed25519 receipt a buyer verifies
offline without trusting us.

**Why it exists.** The rails are solved: x402 (Linux Foundation), AP2 (FIDO Alliance), UCP, ACP,
EMVCo draft. Every one of them verifies a payment. **None of them answers whether this agent should
spend this money on this task.** The failure is documented, not hypothetical: 41 000 correctly
signed payments over one weekend from a pagination bug; a hidden line in a product page changed an
AP2 agent's cart in 56 % of trials; 11 of 47 vendors document a kill switch.

**What is already built** (all verifiable in ten minutes from the repository):

| Component | State |
|---|---|
| Envelope policy, rules E01–E07 | live, deterministic |
| Atomic budget ledger | 100 parallel requests → exactly 50 allowed, proven by test |
| Kill switch + evidence packs | stop < 2s, offline verification, broken chain located by index |
| x402 guard | 1 000 calls at $0.01 with a $5 budget → exactly 500 allowed |
| Receipts | Ed25519, verified without the server |
| Attacks | three, reproducible, refused |
| Tests | 380 passing |
| Public demo | https://karta.rta.lat |

**What a licence buys** (three shapes, same asset):

1. **White-label guard** — the partner's brand in front of the product; budget control becomes a
   feature of their wallet/gateway. From **$25 000/year**, integration support included.
2. **Perpetual non-exclusive licence** — source + right to embed. **$50 000–150 000**, depends on
   scope and exclusivity.
3. **Acqui-hire / asset purchase** — code, tests, brand, domains, pipeline, and the founder for
   90 days. **$150 000–1 000 000**, depends on the buyer's treasury and the strategic fit.

**Why now, and what the buyer gets that they cannot build in a quarter.** The hard part is not the
policy file — it is the evidence chain: mandate → action → spend → receipt, cross-rail, verifiable
by a third party. We have that chain running, tested, with the failure modes documented. A buyer
starting today needs 3–6 months to reach parity, and the window closes as the rails standardise
budget primitives one by one (AWS AgentCore Payments, Cloudflare Wallets, Stripe/Ramp per-agent
cards — each limits its own rail only).

**Honest state.** No paying customers yet; 5 design-partner letters delivered, 0 replies at the
time of writing. What exists is working software, reproducible tests, and a live demo — not revenue.
Any valuation must be argued from the asset, not from the P&L, and we will say that in the room.

**Ask.** One conversation, 30 minutes, with whoever owns agent payments or trust at the buyer.
We bring the demo, the repository, and the numbers. No deck required: the product runs.

Contact: hello@rta.lat · demo https://karta.rta.lat · repo github.com/mrpkk/onchain-ai-agent
