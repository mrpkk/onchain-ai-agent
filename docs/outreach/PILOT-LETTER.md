# S7 — пять design partners: письмо и адресаты

**Правило честности:** партнёром называем только того, кто установил. Отказ — это
данные о ICP, а не провал. Статус каждого адресата ведём здесь же.

Страница, на которую ведёт письмо: `https://karta.rta.lat/partners`
Демо: `https://karta.rta.lat/`

## Письмо (первый контакт, EN)

Отправлять с личной подписи владельца, не с рассылочного адреса. Тема под каждого —
одна строка, без «Partnership opportunity».

```
Subject: one hard stop before your agent overspends

Hi <name>,

I run KARTA — spend control for AI agents. It wraps a task in a signed envelope
(budget, per-call cap, payee allowlist, call limit) and enforces it outside the
model, so a runaway agent gets HOLD or BLOCK instead of a surprise bill.

I looked at <their agent / product> and <one concrete, verifiable observation>.
If that agent pays for <APIs / data / other agents>, the failure mode is simple:
one loop, forty thousand calls, no hard stop.

We are taking five design partners for a free 30-day pilot:
- a review of one real spend flow in your agent;
- an envelope config you can apply the same day;
- a sample evidence package (every decision, stop and resume, verifiable offline);
- direct line to me for 30 days. No fee, no card.

Worth a 30-minute call? If yes, reply with two windows and I will send an invite.

<name>, KARTA
https://karta.rta.lat/partners
```

**Персонализация обязательна:** `<one concrete observation>` заполняется только тем,
что реально видно на их сайте/в докладе/в репозитории. Не видел — не пишем.

## Пять адресатов (проверены 26.10.2026)

| # | Кто | Почему подходит | Канал | Статус |
|---|---|---|---|---|
| 1 | **Smithery** — `https://smithery.ai` | реестр MCP-серверов, через него ставят инструменты агентам | форма/страница контактов, Discord | не отправлено |
| 2 | **Glama** — `https://glama.ai` | каталог MCP-серверов, аудитория — разработчики агентов | форма добавления/контакт | не отправлено |
| 3 | **Coinbase Developer Platform (x402)** — `https://docs.cdp.coinbase.com` | агенты платят за API через x402; ровно наш сценарий траты | GitHub issues / Discord CDP | не отправлено |
| 4 | **Nevermined** — `https://nevermined.io` | платежи и биллинг для AI-агентов | форма на сайте | не отправлено |
| 5 | **Virtuals Protocol** — `https://virtuals.io` | агенты с кошельками в экосистеме | форма/Discord | не отправлено |

Запасные (если первые пять молчат ≥5 дней): Olas (`https://olas.network`),
Fetch.ai (`https://fetch.ai`). У всех — 307/301-редиректы, домены живые.

**Точные адреса почты не выдумываем.** Если на сайте только форма — отправляем
форму, а в тексте оставляем email владельца для ответа.

## Последовательность

1. День 0 — письмо (или форма) с персонализацией.
2. День 3 — короткий follow-up в той же ветке: «успел ли посмотреть, могу показать
   на вашем сценарии за 15 минут».
3. День 7 — закрываем без обид: «если сейчас не время, вернусь через месяц».
4. Ответ «да» → звонок → конфиг конверта → установка → **только после установки**
   просим разрешение назвать партнёром и короткую цитату.

## Что считаем результатом S7

- 5 подписанных писем о пилоте (бесплатно, с именем) — DoD спеки;
- ≥3 довели установку до конца;
- 1 публичный отзыв;
- каждая заявка через страницу попадает в `~/.local/share/karta-demo/pilot-requests.jsonl`.
