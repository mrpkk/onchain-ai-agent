# Готовые посты — публикуются с аккаунтов владельца

Правило: один пост = один факт + одна ссылка. Без «revolutionary», без выдуманных клиентов.
В каждом — честная строка «pre-revenue». Это не скромность, это фильтр: скептики дочитывают.

---

## 1. X (Twitter) — thread из 5 постов

**1/5**
> Every AI agent payment rail now verifies the payment.
> None answers: should this agent spend this money on this task, right now?
>
> We checked 2 500 MCP servers. 72 move money. Zero mention a kill switch or a task budget.

**2/5**
> The failure is not a stolen key. It's 41 000 correctly signed payments in one weekend — a pagination bug, every call legal, the budget gone.
> A per-call limit never notices. A task budget does.

**3/5**
> KARTA: one signed envelope per task — budget, allowed payees, no subscriptions, expiry.
> Enforced outside the model, so a prompt-injected agent cannot sign around it.
> Kill switch stops one agent in under two seconds.

**4/5**
> Every allowed spend returns an Ed25519 receipt a third party verifies offline — without trusting us.
> Three attacks are reproducible in ten minutes; the policy refuses all three.
> https://karta.rta.lat/attacks

**5/5**
> Glama rated the MCP connector A. 413 tests. Free tier, no signup.
> Honest state: pre-revenue, 0 paying customers — we are looking for five teams to try it for 30 days.
> https://karta.rta.lat

---

## 2. Reddit — r/mcp (пост, не реклама)

**Title:** We surveyed 2 500 MCP servers: 72 move money, none mentions a kill switch

**Body:**
> Pulled the official registry today (2 500 servers, snapshot in the repo) and split the ones that describe a payment, wallet or x402 function. 72 of them.
>
> Of those 72:
> - 11 mention a budget
> - 0 mention a limit or a cap
> - **0** mention a kill switch or an emergency stop
> - **0** describe a per-task budget
> - 2 mention a receipt
>
> Caveat: these are descriptions, not code. Absence of a word is not absence of a feature — it means the vendor didn't think it was worth a line, which is itself a signal.
>
> The script is nine lines of Python over a public API, feel free to re-run it: https://karta.rta.lat/report
>
> I built the missing layer (task envelope + kill switch + offline-verifiable receipts), and three attacks you can run yourself: https://karta.rta.lat/attacks. Pre-revenue, looking for teams to break it.

---

## 3. LinkedIn — пост для B2B

> Агенты уже платят: за данные, за API, за ончейн-действия. Рельсы это решили — x402 ушёл в Linux
> Foundation, AP2 в FIDO Alliance, UCP и ACP закрывают чекаут.
>
> Не решено другое: должен ли этот агент тратить эти деньги на эту задачу прямо сейчас.
>
> Мы проверили 2 500 MCP-серверов: 72 двигают деньги, и ни один в описании не упоминает kill switch
> или бюджет задачи.
>
> KARTA закрывает это: подписанный конверт на задачу, принуждение вне модели, остановка агента за
> две секунды, квитанция Ed25519, которую аудитор проверяет офлайн. Glama оценил A, 413 тестов.
>
> Ищу 5 команд на бесплатный 30-дневный пилот: один процесс, реальные цифры, честный разбор.
> karta.rta.lat/pilot

---

## 4. Hacker News — заголовки (выбрать один)

- `Show HN: Spend control for AI agents — a budget per task, not per call`
- `Show HN: I surveyed 2 500 MCP servers — none mentions a kill switch`
- `The rails verify the payment; nobody checks the task`

Правило HN: ссылка на страницу с фактами (`/report` или `/attacks`), не на главную; в первом
комментарии — что это, чего не делает, и что просим (5 команд). Без «мы» в заголовке.

---

## 5. dev.to — статья (600–800 слов)

Заголовок: **«Your agent can pay now. Here is the layer that decides whether it should.»**

Структура:
1. Факты: 41 000 платежей, 56 %, 11 из 47, 72 против 0 (наши замеры).
2. Почему рельсы этого не решают (цитата логики AP2: агент может быть скомпрометирован).
3. Что такое конверт задачи (с JSON-примером).
4. Три атаки, команды.
5. Честно: pre-revenue, чего не делаем (не двигаем деньги, не держим ключи).
6. CTA: пилот.

---

## 6. Порядок публикаций (чтобы не сжечь аккаунт)

| День | Что | Почему так |
|---|---|---|
| 1 | X-thread | самый низкий порог, сразу видно реакцию |
| 2 | Reddit r/mcp | там сидят те, кто ставит MCP-серверы |
| 4 | LinkedIn | B2B-аудитория, другой тон |
| 5 | HN Show | только после постов, иначе снесут как рекламу |
| 7 | dev.to | SEO-хвост, живёт долго |

Между публикациями — отвечать на комментарии **фактами и командами**, а не «давайте созвон».
Один пост без ответов хуже, чем отсутствие поста.
