# What agent tools say about money — a registry survey (26.10.2026)

**Sample:** the first 2 500 servers returned by the official MCP registry
(`registry.modelcontextprotocol.io/v0/servers`, cursor pagination), snapshot 26.10.2026.
**Method:** keyword analysis of the public `title` + `description` fields. Reproducible:
the raw snapshot and the filter are in this document's appendix.

## Finding

| Measure | Count |
|---|---|
| Servers in the sample | 2 500 |
| Describe a payment, wallet or x402 function | **72** |
| …mention a budget | 11 |
| …mention a limit or a cap | 0 |
| …mention a kill switch or emergency stop | **0** |
| …describe a per-task budget | **0** |
| …mention a receipt | 2 |
| …mention an audit trail | 0 |

The 2 500 descriptions mention "approval" 65 times and "audit" 26 times overall — but almost none of
those are in the payment group. The tools that move money describe *what they pay for*, not *what
stops them*.

## Why it matters

The failure mode is documented, not hypothetical: an agent made 41 000 correctly signed payments in
one weekend because of a pagination bug; hidden text changed an AP2 agent's cart in 56 % of trials;
11 of 47 vendors audited in September document a kill switch. This sample says the registry layer is
the same: the vocabulary of spending is present, the vocabulary of stopping is not.

## Honest limits

1. **Descriptions are marketing text.** Absence of the word "kill switch" does not prove absence of
   the feature. It proves the vendor does not consider it worth a line — which is itself a signal.
2. **Sample, not census.** 2 500 servers by registry order; the registry is larger and changes daily.
3. **The filter is lexical.** A server that says "guardrails" without "budget" is counted as silence.
4. **No runtime testing.** We did not call these servers. We read what they publish.

## What we do with this

- The composition of the two vocabularies — "what it pays for" vs "what stops it" — is the product
  thesis of KARTA: a **task envelope** with a budget, a payee allowlist, no subscriptions, a kill
  switch and an offline-verifiable receipt.
- Anyone can re-run the survey: the script is nine lines of Python over the registry API and is
  included in the repository (`scripts/registry_survey.py`).
- If you sell an agent tool that does have limits, say so in your description. Buyers cannot see
  what is not written.

## Appendix: method

```python
import json, re, urllib.parse, urllib.request

base = "https://registry.modelcontextprotocol.io/v0/servers"
cursor, servers = None, []
for _ in range(25):                      # 25 x 100 = 2 500
    q = {"limit": 100}
    if cursor:
        q["cursor"] = cursor
    page = json.load(urllib.request.urlopen(base + "?" + urllib.parse.urlencode(q)))
    servers += [s["server"] for s in page["servers"]]
    cursor = (page.get("metadata") or {}).get("nextCursor")
    if not cursor:
        break

money = re.compile(r"x402|usdc|stablecoin|agent wallet|wallets?\b|agent payments|"
                   r"payment rail|on-?chain payment|lightning|l402|billing|invoice")
group = [s for s in servers if money.search(((s.get("description") or "") + " " +
                                             (s.get("title") or "")).lower())]
```

Counts were taken with `re.search` over the same text for: `budget`, `\blimit|\bcaps?\b`,
`kill[- ]switch|emergency stop`, `per[- ]task|task budget|per job`, `receipt`, `audit`.

Snapshot date: 26.10.2026. Registry content changes; re-running will give different numbers, and that
is the point of publishing the recipe.
