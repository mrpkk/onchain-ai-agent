# Ready-to-post text: "Three ways an agent with a wallet loses money"

Готово к публикации от твоего аккаунта (HN / X / LinkedIn / r/mcp). Ничего править не нужно.
Ссылки уже живые. Все числа проверяемы командами из текста.

---

**Title (HN/Reddit):** Three ways an agent with a wallet loses money, and the one object that stops it

**Body:**

Every payment rail for AI agents is now solved or being solved: x402 went to the Linux Foundation,
AP2 to the FIDO Alliance, UCP and ACP cover checkout, EMVCo published a draft. They answer one
question — *can this payment be verified*.

None of them answers the other one — *should this agent spend this money on this task, right now*.
That gap is where the money actually goes, and it is not theoretical.

**1. The loop that is always right.** An agent paginating a paid API through a bug kept requesting
the same pages. Over a weekend: 41 000 calls, each correctly signed and settled. A per-call limit
never notices, because every call was legal. The budget was gone.

**2. The vendor nobody approved.** A scraped page said the dataset was available "for licensed
purchase" from an unknown vendor. The agent bought it. In a September 2026 preprint, hidden text in
product descriptions made an AP2 shopping agent assemble a different cart than the one shown to the
user in 56 % of trials — the mandate signed it faithfully.

**3. The subscription nobody asked for.** "Minimise cost" is not permission for a recurring charge.
An agent subscribed to a discounted plan and kept it for months.

The common shape: **the model is asked to be the policy**, and the model can be persuaded. AP2's own
security guidance assumes the agent may be compromised and calls prompt-injection prevention
infeasible — so the policy has to live outside the model.

I built that layer and made it boring on purpose. One signed envelope per task: budget, allowed
payees, no subscriptions, expiry, cost centre. The gateway holds the key, so the agent asks and
cannot sign around the answer. A kill switch stops one agent in under two seconds. Every spend
leaves an Ed25519 receipt an auditor verifies offline, without trusting the vendor.

You can check it without signing up:

- three attacks, one command each:
  `github.com/mrpkk/onchain-ai-agent/tree/feature/v2-modernization/attacks`
  (each script exits 0 when the attack is refused, 1 when money could move)
- live demo, four deterministic scenarios: `karta.rta.lat`
- install: clone, venv, uvicorn — ten minutes, then run the attacks yourself

Two honest limits: this is the decision layer, not a settlement rail, and mainnet payment execution
is off by default. What is proven is the invariant — 100 parallel spend requests against a 50 ×
$0.05 budget produce exactly 50 approvals, and a pagination loop stops at the boundary instead of
at bankruptcy.

The object that is missing in every rail today is a **task-bound spend envelope**. If you are
building agents that pay, I would rather hear where this breaks than sell you a licence. Five teams
get 30 days free, with one honest paragraph in return.

`karta.rta.lat` · `hello@rta.lat`

---

## Куда постить (в этом порядке)

| Площадка | Формат | Почему |
|---|---|---|
| **Hacker News** (`news.ycombinator.com/submit`) | ссылка на `karta.rta.lat` + заголовок выше | твой браузер постит без rate-limit, который ловит туннель |
| **r/mcp, r/AI_Agents** | тот же текст | там сидят люди, которые ставят MCP-серверы |
| **X** | первые 3 абзаца + ссылка на атаки | короткий крючок «41 000 платежей» |
| **LinkedIn** | тело целиком | там партнёрские менеджеры, не разработчики |

## Правила, чтобы не убить эффект

1. Не просить апвоуты и не постить дважды в один день.
2. Отвечать на комментарии фактами и командами, а не «дайте созвон».
3. Если пост не зашёл — не переписывать, а идти в r/mcp с другим углом (там меньше шума).
