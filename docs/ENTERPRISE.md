# KARTA — enterprise security pack

**Purpose:** answer the 12 questions a platform, protocol, or RWA issuer asks before a pilot.
**Status:** product is live in demo form; **0 paying customers**, **0 design partners**. This pack is
evidence of controls, not a certification claim.

**Live demo:** <https://rta.lat/karta> · **Public MCP:** `https://rta.lat/karta/mcp` ·
**Receipt verify:** <https://rta.lat/karta/verify> · **Evidence:** `/karta/evidence/<id>`

**Legal:** SLA and DPA sections are **drafts**. They require legal review before signature. No
SOC 2, ISO 27001, or regulatory approval is claimed.

---

## The 12 questions

| # | Question | Answer (as built) | Evidence |
|---|---|---|---|
| 1 | Who owns the keys? | The gateway, never the model. Agent asks;KeyVault/Fernet stores the key outside the prompt and outside the receipt. | `backend/src/security/keyvault.py`; no key in logs/responses |
| 2 | Where is the policy enforced? | Outside the model: deterministic Dharma Engine → `ALLOW / HOLD / BLOCK` + rule number. | `backend/src/security/envelope.py` E01–E07; demo `/karta` |
| 3 | Can the model override a block? | No. A `BLOCK` is not re-askable from the model; only a human approval surface can change the outcome. | `backend/src/agent/core.py`; SPEC v4 invariant #3 |
| 4 | What if the model is compromised? | The task envelope caps budget, per-call amount, call count, payees, subscriptions and expiry. Prompt injection cannot grant a new payee. | `/karta/api/v1/x402/check`; E02/E03/E04/E05/E06 |
| 5 | How do you stop an agent? | Operator kill switch: `POST /karta/api/v1/kill`; demo/API/MCP return `503 kill_switch`; runtime hard-kill; no auto-resume. | `backend/src/security/killswitch.py`; test <2 s |
| 6 | Where is the audit log? | Sakshi Log: append-only HMAC chain, hash + prev_hash per event; export JSON/CSV. | `backend/src/security/sakshi.py`; `docs/SECURITY.md` |
| 7 | How can we verify without trusting you? | Ed25519-signed receipts and evidence packages; public key inside; `/karta/verify` checks in the browser; server can be offline. | `security/evidence.py`; `31c2d1c`; `/karta/verify` |
| 8 | What data leaves the environment? | Demo metrics: scenario id, verdict, rule, ref, evidence id. No keys, prompts, or wallet secrets. Hosted mode is configurable; define retention in DPA. | `/karta/metrics`; evidence package excludes payloads |
| 9 | What is the blast radius of one task? | One envelope: `budget_total`, `per_call_max`, `calls_max`, allowlist, commitments, expiry, approval threshold. A failure is capped at that task. | `docs/ARCHITECTURE.md`; E01–E07 |
| 10 | Multi-tenant isolation? | API/MCP data is scoped to the owner API key; foreign agent ids return 404. The public demo is stateless and stores no tenant data. | `backend/src/mcp/server.py`; tests |
| 11 | What SLA can you offer? | Draft: 99.5% monthly for hosted pilot, 1-business-day response, incident report within 48 h. **Not yet measured; legal review required.** | SLA draft below |
| 12 | Which certifications? | None claimed. We provide controls, logs, receipts and a threat model; a buyer’s security team performs its own review. | `docs/SECURITY.md`, `docs/THREAT_MODEL.md` |

---

## Control map

| Control | Owner | Where | How to prove |
|---|---|---|---|
| Budget limit | task envelope | `security/envelope.py` + ledger | `POST /karta/api/v1/x402/check`; receipt |
| Payee allowlist | task envelope | E03 | unknown host → `BLOCK/E03` |
| Subscription control | task envelope | E02 | subscription → `BLOCK/E02` |
| Call-count cap | task envelope | E05 | 41 000 calls → `BLOCK/E05` |
| Emergency stop | operator | `/api/v1/kill` | `/health` state; 503 on verdict/spend |
| Key custody | gateway | KeyVault/Fernet | no key in prompt/log/receipt |
| Audit trail | Sakshi | HMAC chain | export + `verify_chain` |
| Receipt integrity | Ed25519 | `ledger.reserve` | `/karta/verify` → VALID/INVALID |
| Evidence package | Ed25519 | `/api/v1/evidence` | offline `verify_bundle` |
| Public demo isolation | stateless | demo app | no auth, no tenant data |

---

## Deployment options

| Mode | What | Notes |
|---|---|---|
| **Public demo** | `rta.lat/karta` | read-only, no funds, rate-limited; for evaluation |
| **Hosted pilot** | KARTA control plane + your API key | Team/Pilot; retention and region by agreement |
| **Self-hosted** | Docker + Postgres/SQLite; your keys | Enterprise; no custody; your security team owns the perimeter |
| **Embedded** | `check_spend` MCP + HTTP guard | agent/platform integration; no UI required |

**No custody, no money transmission, no token.** KARTA decides; the payment rail executes.

---

## Pricing (one table)

| Tier | Price | What |
|---|---:|---|
| Open | $0 | MCP, 20 checks/day, demo, local run |
| Team | **$99/mo** (India $49) | hosted control plane, 5 000 checks/mo, 5 envelopes, evidence export |
| Pilot | **$2 500** one-time, 14 days | install, 3 policies, 1 integration, findings report, 30 days support |
| Enterprise | **from $25 000/year** | white-label, SSO, private deployment, 5 checks in one entry, SLA |
| Retainer | **$1 500/mo** | monthly reconciliation, new rules, incident review |

---

## SLA draft (LEGAL REVIEW REQUIRED)

- Availability target: **99.5% monthly** for hosted pilot (not yet measured; no historical uptime claim).
- Support: written only; first response within **1 business day**; incident report within **48 h**.
- Exclusions: customer network, third-party RPC/payment rails, force majeure.
- Credits: to be defined by counsel; do not promise credits before they are funded.
- No 99.99% claim, no “bank-grade” claim, no regulatory approval claim.

## DPA draft (LEGAL REVIEW REQUIRED)

- Roles: customer = controller; KARTA = processor for hosted mode.
- Data: account identifiers, policy config, receipts, audit metadata; no wallet private keys.
- Sub-processors: hosting/RPC providers to be listed before signature.
- Retention: configurable; default 30 days for demo, 12 months for paid audit unless agreed.
- Deletion: written request; receipts may remain in append-only audit if required by law.
- International transfers: to be documented per customer; no claim of adequacy.
- Breach notice: without undue delay, target 72 h after confirmation.

---

## Evidence sample

1. Run a demo scenario at <https://rta.lat/karta>.
2. Open `/karta/api/v1/evidence` → Ed25519-signed bundle (`karta-evidence-v1`, public key inside).
3. Open `/karta/evidence/<evidence_id>` → the same bundle rendered for a reader.
4. Verify offline with `security.evidence.verify_evidence(bundle)` — no server, no network;
   tamper one record → **INVALID** and the broken index.

This is the artifact a buyer can put in front of an auditor without trusting KARTA’s dashboard.

---

## What we do not claim

- No statutory audit, legal opinion, or regulatory licence.
- No guarantee that a provider refunds money.
- No “100% safe” or “unhackable”.
- No named customers or partners until they have installed and agreed in writing.
- No SLA credits until counsel and finance approve them.

**Contact:** written only — `maxim.pkk@gmail.com`.
