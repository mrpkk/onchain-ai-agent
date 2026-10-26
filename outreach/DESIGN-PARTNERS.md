# Design partners — S7

**Цель слайса:** 5 подписанных писем о пилоте, ≥3 установки. Пилот бесплатный: партнёр даёт
имя и честную обратную связь, мы — guard + evidence-пакет. Никаких шаблонных рассылок:
в каждом письме конкретная причина, почему это нужно именно им.

| # | Кто | Почему он | Канал | Статус |
|---|---|---|---|---|
| 1 | **Smithery** (реестр MCP) | тысячи платных инструментов и ни одного бюджета на задачу у покупателя | `contact@smithery.ai` | **отправлено 26.10** |
| 2 | **Claw402** (x402-шлюз) | покупатель платит по вызову; лимит на вызов не защищает от цикла | `claw402.ai/providers` (форма); GitHub issue отклонён 403 (токен без прав) | нужна форма в браузере |
| 3 | **x402scan / Merit Systems** | видит объёмы, но не политику: наш пакет закрывает вопрос «за что списали» | email на сайте не публикуется; GitHub-токен без прав на чужие issues (403) | нужен браузер для формы |
| 4 | **Glama** (каталог + gateway) | проксирует вызовы — единственное правильное место для бюджета | `support@glama.ai` (страница Support) | **отправлено 26.10** |
| 5 | **CDP / x402 (Coinbase)** | эталонный рельс; guard логично ставить рядом с их SDK | форум разработчиков | нужен канал |

## Правила

1. Одно письмо — один конкретный повод. Никаких «мы делаем ИИ для бизнеса».
2. Не выдумывать факты о получателе: если не проверено — писать «видно снаружи».
3. Не называть партнёром того, кто не поставил. Согласие на пилот ≠ партнёр.
4. Отказ фиксировать с причиной: это данные для ICP, а не провал.
5. Отправка — 15 писем в день максимум (G3), с записью в таблицу.

## Письмо №1 (отправлено, для повторного использования как основа)

Тема: *A spend guard for Smithery tools — 5-team pilot, no cost*

> Hi,
>
> I'm Maxim, building KARTA — a spend-control layer for agents that use paid tools.
>
> The problem your registry makes visible: an agent with a wallet can make thousands of valid
> payments before anyone notices. We reproduced the October case — 41 000 correctly signed calls
> in one weekend from a pagination bug — and it stops at the task budget, not at the payment.
>
> What KARTA adds around a tool call: one signed envelope per task (budget, allowed payees, no
> subscriptions, expiry); the decision is made outside the model, so the agent cannot sign around
> it; a kill switch that stops one agent in under two seconds; an Ed25519 receipt the buyer can
> verify offline, without trusting us.
>
> Everything runs today: https://karta.rta.lat (live demo, no signup) and three attacks you can run
> locally: https://github.com/mrpkk/onchain-ai-agent/tree/feature/v2-modernization/attacks
>
> The ask: five teams from your registry as design partners for 30 days. Free, no revenue share,
> no lock-in; they get the guard plus an evidence pack, we get a name and honest feedback on what
> breaks. If it works, the natural next step is a "budget-controlled" badge on paid servers.
>
> One question so I don't waste your time: who owns trust and safety for tool installs at
> Smithery — you or the server authors?
>
> — Maxim
> KARTA · https://karta.rta.lat · hello@rta.lat

## Что считается результатом

| Метрика | Цель | Сейчас |
|---|---|---|
| Писем отправлено | 5 | 2 |
| Ответов | ≥2 | 0 |
| Согласий на пилот | 3 | 0 |
| Установок | 3 | 0 |
