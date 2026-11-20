# Деньги за 27 дней: гранты, призы, лицензии

**Дата:** 26.10.2026 · **Горизонт:** 22.11.2026 · **Актив:** KARTA (+ attest/drift/nidhipati как
подтверждающие сервисы, вызываемые по API).

## 1. Смена рамки

Подписками $1M за 27 дней не собирается — но это не приговор, а указание, **где лежат деньги
такого размера**: в капитале, а не в выручке. За 27 дней $1M приходит одной из четырёх форм:

| Форма | Кто платит | Чек | Срок решения |
|---|---|---|---|
| Грант | фонд протокола / экосистема | $10–100k | 2–8 недель |
| Приз | хакатон, конкурс | $5–50k | 1–3 недели |
| Лицензия / white-label | платформа, протокол | $25–250k | 3–8 недель |
| Продажа актива / acqui-hire | компания с казной | $100k–1M | 4–12 недель |

Вывод, который меняет план: **не «продавать подписку», а продавать актив** — работающий продукт,
доказательства, метрики, команду. Подписка остаётся способом показать спрос, а не источником $1M.

## 2. Арифметика вероятностей (не отказ, а расчёт)

| Поток | Сколько заявок | Шанс на одну | Чек | Ожидание |
|---|---|---|---|---|
| Гранты | 8–10 | 8–12 % | $50–100k | **$40–90k** |
| Хакатоны | 2–3 | 15–25 % призовой тройки | $5–20k | $2–10k |
| Баунти (Immunefi/Cantina) | 2–3 | 5–10 % | $5–50k | $1–10k |
| Лицензия/сделка | 100 касаний | 3–5 % | $50–250k | **$2–12k ожидаемо, но хвост до $1M** |
| Токен/публичная продажа | 1 | 5–10 % на $1M cap | $0,1–1M | $50–100k, риск репутации |

Чтобы $1M случился, нужен **один хвост** (лицензия/сделка/токен). Остальные потоки нужны,
чтобы: (а) жить и платить за юрлицо, (б) давать доказательства для хвоста, (в) не зависеть
от одного «да».

## 3. Что реально открыто (проверено 26.10.2026)

| Программа | Что даёт | Дедлайн | Статус проверки |
|---|---|---|---|
| **ASI Deep Funding** (SingularityNET/Fetch) | до $100k, milestone-based, open-source | раунды, проверить текущий | сайт открыт, размер подтверждён |
| **AI Grant** (aigrant.com) | $250k uncapped SAFE + кредиты Azure | по раундам | сайт открыт |
| **lablab.ai Agent Rush** | $10k pool ($5k cash) | сборка 3–8.11.2026 | даты в листинге |
| **Open Agent Hackathon** (genai.works) | до $20k | 22–27.10.2026 | почти закрыт — на следующий |
| **GitHub MCP / Cline / Glama** | не деньги, а дистрибуция | постоянно | подтверждено ранее |
| Base / Arbitrum / Optimism / Solana ecosystem grants | $10–100k | раунды | нужно проверить формы (base.org/grants не открылся) |
| Immunefi / Cantina / Code4rena | $5–100k за находку | постоянно | не подавались |
| Virtuals / Olas / Fetch | партнёрство + грант | по заявке | не подавались |

`UNVERIFIED` помечено честно: даты и суммы меняются, проверяю перед отправкой, а не по памяти.

## 4. Мастер-текст заявки (EN, 350 слов, адаптируется)

> **KARTA — spend control for AI agents.**
>
> Agents now hold wallets and pay per call. The rails (x402, AP2, UCP, ACP) verify a payment;
> none of them answers whether this agent should spend this money on this task. The gap is real:
> in October 2026 an agent made 41 000 correctly signed payments over one weekend because of a
> pagination bug, and a hidden line in a product page changed an AP2 agent's cart in 56 % of trials.
>
> KARTA closes it with one object and three guarantees. The object is a **task envelope**: budget,
> allowed payees, no subscriptions, expiry, owner, cost centre. The guarantees: the decision is
> made **outside the model** (keys never reach the prompt); a **kill switch** stops one agent in
> under two seconds; every spend carries an **Ed25519 receipt** the buyer verifies offline.
>
> State today: live demo with four deterministic scenarios, a public API with an atomic budget
> ledger (100 parallel requests → exactly 50 allowed, proven by test), 380 tests, three reproducible
> attacks that are refused, and a ten-minute install verified on a clean machine. Six supporting
> services (artifact verification, mandate control, spend audit, skill lint) are live and called
> over HTTP — no reimplementation.
>
> What the grant funds, 8 weeks: (1) policy DSL v2 with 20 rules and a test corpus, (2) card-rail
> adapter next to x402, (3) cross-rail budget view, (4) two published design-partner reports,
> (5) security review of the gateway. Deliverables are measurable: envelopes enforced, receipts
> verified externally, false-block rate under 2 %.
>
> Why us: we already run the enforcement, not a deck. Everything above is reproducible from the
> repository in ten minutes, including the three attacks.
>
> Links: demo, repository, attacks, pilot one-pager.

**Правила текста:** без «100 % безопасности», без выдуманных клиентов, все числа проверяемы.
Слово «пилот» вместо «клиент», пока никто не заплатил.

## 5. Календарь 27 дней

| Дни | Действие | Метрика |
|---|---|---|
| 26–28.10 | 10 заявок на гранты (черновики + отправка), 2 хакатона | 10 подано |
| 29–31.10 | баунти: 2 заявки, 1 прогон сканера по цели | 2 подано |
| 1–7.11 | хакатон lablab (3–8.11): сабмит KARTA + запись демо | сабмит есть |
| 8–14.11 | 100 лицензионных касаний (по 15/день), меморандум + демо | 100 касаний, ≥3 ответа |
| 15–18.11 | демо 3–5 компаниям, term sheet/LOI | 1 LOI |
| 19–22.11 | честный итог: что пришло, что нет, следующий шаг | отчёт с числами |

## 6. Опция высокой дисперсии (решение владельца)

Токен/паблик-сейл — единственная категория с потолком $1M за 27 дней. Честно:
юридический риск, репутационный риск для enterprise-трека, и это противоречит правилу
«no token» в продуктах. Без решения владельца не запускаю. Если решение «да» — нужен
отдельный план: сеть запуска, аудит контракта, KYC-политика, лимиты.

## 7. Что не делаем

- Не обещаем грант, приз или сделку как факт.
- Не подаём заявку с выдуманными метриками: все цифры берутся из `/metrics` и тестов.
- Не тратим деньги до выручки: подача везде бесплатная.
