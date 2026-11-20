# Three attacks you can reproduce in ten minutes

KARTA's claim is narrow and testable: **the model decides what to ask for; the envelope decides
what is allowed.** These three scripts are the attacks from the market research of October 2026,
reduced to the smallest reproducible form.

```bash
cd /media/Sruti/iamthat/work/onchain-ai-agent
python3 attacks/prompt_injection_payee.py    # a scraped page asks for a new vendor
python3 attacks/tool_poisoning_amount.py     # a tool returns 1000x the real price
python3 attacks/runaway_loop.py              # 41 000 correct payments, one bug
```

Each script exits `0` when the attack is refused and `1` when money could have moved.

| Attack | Real case (17.10.2026) | KARTA's answer | Rule |
|---|---|---|---|
| New vendor from injected text | agent bought a $940 report from a vendor nobody knew | payee allowlist, new payees refused | `E03` |
| Poisoned tool inflates the amount | — | per-call cap checked outside the model | `E04` |
| Runaway loop | 41 000 paid calls in one weekend, every payment valid | budget belongs to the task, not the call | `E05` / `E06` |

## What this does *not* prove

- No real funds move here: this is the decision layer, not the settlement rail.
- Mainnet payment execution is off by default (STOP-gate G2).
- The scripts use the same `evaluate()` the public API and the demo use — if the policy changes,
  the attacks are the first thing that should fail.

## Why it matters to a buyer

A signature proves a payment was authorised. It does not prove the purchase was sensible.
Every rail in 2026 (x402, AP2, UCP, ACP) verifies the payment; none of them enforces the
task-bound budget. That gap is the product.
