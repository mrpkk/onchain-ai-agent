# KARTA — how to pay (USDC on Base), and what you get for it

**Status:** no paying customers yet. This document exists so that the first "yes" does not wait
for paperwork. Nothing here is a subscription trap: one invoice, one scope, one refund rule.

## Prices

| Item | Price | What is included |
|---|---|---|
| Pilot (30 days) | **$2 500** | installation, 1–3 envelopes, guard in front of live calls, evidence pack, written review |
| Team | **$99 / month** (India $49) | hosted control plane, 5 000 checks/month, 5 envelopes, evidence export |
| Enterprise | **from $25 000 / year** | white-label, SSO, private deployment, SLA, 5 checks in one entry point |
| Retainer | **$1 500 / month** | monthly reconciliation, new rules, incident review |

First three pilots: same price, no "discount for friends". A discount would make the review less
honest, and the review is the actual deliverable.

## How to pay

- **Asset:** USDC (native or bridged, both accepted on Base).
- **Network:** Base (chain id 8453). Other networks by agreement — write first.
- **Address:** `0xefCD…` — **the full address is sent in the invoice email**, never only in a chat.
- **Memo / reference:** invoice id (`KARTA-YYYYMM-###`) plus your company name.

**Verify the address before sending:** the first six and last four characters must match the ones
in the invoice email. If they differ, stop and write to `hello@rta.lat`. Address substitution is
the oldest trick in crypto invoicing.

## What happens after payment

| Time | Step |
|---|---|
| ≤ 24 h | we confirm the transaction hash on Basescan and send a written confirmation |
| ≤ 24 h | invoice marked paid, kickoff call scheduled |
| Day 1–2 | first envelope live |
| Day 30 | written review: what held, what broke, the numbers (blocked payments, prevented spend, false blocks) |

## Refund rule

If we do not deliver the day 1–2 item (one live envelope) within five business days of payment,
you get **100 % back** in USDC to the address you paid from. No discussion, no forms.
After the envelope is live, the pilot is non-refundable — the work has been done.

## What we do not do

- We do not hold, custody, or route your funds. The invoice is payment for services, not a deposit.
- We do not issue a token, and nothing here is an investment.
- We do not promise "100 % safety". The guard is deterministic; the policy is only as good as the
  envelope you write. The review will say so in plain words.

## Invoice template

```
KARTA — invoice KARTA-202611-001

To:      <company>, <billing contact>
From:    Maxim (individual), hello@rta.lat
Date:    <YYYY-MM-DD>
Scope:   Pilot, 30 days — one workflow, 1–3 envelopes, guard, evidence pack, written review
Amount:  2 500.00 USDC
Network: Base (chain id 8453)
Address: <full address — verify first 6 / last 4>
Due:     on receipt

Deliverables (day 1–2): one live envelope for one real workflow.
Refund: full, if that deliverable is missing after five business days.
```

## Notes for the buyer's finance team

- We are an individual, not a company: there is no VAT and no corporate entity behind the invoice.
  If your procurement requires a legal entity, say so before paying — this is the honest limit of
  the current setup (an offshore entity is planned only after first revenue).
- Payment in USDC is final on-chain; the refund rule above is our commitment, not a chargeback right.
- A signed PDF invoice is available on request; the numbers are the same as in this document.
