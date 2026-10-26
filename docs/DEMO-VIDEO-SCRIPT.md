# Demo video — 2 minutes, no voice-over needed

Цель: человек, который никогда не слышал о KARTA, за 120 секунд видит проблему, решение и
доказательство. Запись — только экран, без лица. Субтитры обязательны (EN), звук — тишина.

## 0:00–0:15 · Проблема (3 кадра)

Экран: терминал, `python3 attacks/runaway_loop.py`.

> «Every payment here is valid. Signed, verified, settled. 41 000 of them in one weekend —
> because of a pagination bug. A per-call limit never notices. The budget was gone.»

В кадре вывод: `allowed: 2000  blocked: 39000  spent: 100.00  remaining: 0.00`.

## 0:15–0:35 · Что такое конверт

Экран: `docs/PILOT.md` или демо-страница, сценарий «41 000».

> «KARTA gives the agent one envelope per task: a budget, allowed payees, no subscriptions,
> an expiry. The budget belongs to the task, not to the call.»

Показать блок вердикта: `BLOCK / E05 / calls_exhausted / 2000 calls permitted, requested #41001`.

## 0:35–0:55 · Три атаки, все отказаны

Три команды подряд, по 5 секунд:

1. `prompt_injection_payee.py` → `BLOCK E03`
2. `tool_poisoning_amount.py` → `BLOCK E04`
3. `runaway_loop.py` → стоп на границе

> «New vendor from injected text, a tool that inflates the price a thousand times, a loop that
> never stops. Same answer: the model asks, the envelope decides.»

## 0:55–1:15 · Ключи и остановка

Экран: `/api/v1/kill` → `active: true`; затем `spend` → `503 kill_switch`.

> «The agent never holds the key, so it cannot sign around the policy. One operator can stop one
> agent in under two seconds — without stopping the fleet.»

## 1:15–1:35 · Доказательство

Экран: `scripts/verify_evidence.py /tmp/bundle.json` → exit 0; затем подмена одного поля → exit 3.

> «Every action leaves an Ed25519 receipt your auditor verifies offline, without trusting us.
> Change one field — the chain breaks, and it tells you exactly where.»

## 1:35–2:00 · Просьба

Экран: `https://karta.rta.lat`, затем `docs/PILOT.md`.

> «It runs today: 380 tests, a live demo, a ten-minute install. We are looking for five teams with
> agents that pay — free for 30 days, with one honest paragraph in return: where it breaks.
> karta.rta.lat.»

## Технические требования к записи

| Что | Значение |
|---|---|
| Разрешение | 1920×1080, тёмная тема (как демо) |
| Шрифт в терминале | 16–18 pt, чтобы читалось на телефоне |
| Длительность | 110–120 секунд, не больше |
| Субтитры | вшитые, EN; текст — дословно из блоков выше |
| Музыка | нет (тишина лучше плохой музыки) |
| Файл | `demo/karta-2min.mp4`, < 40 МБ, плюс `poster.png` |

## Где использовать

1. Первое письмо партнёру — ссылка, а не вложение.
2. Заявка на грант и хакатон — обязательное поле «demo video».
3. Страница `/pilot` и профиль в каталогах.

## Чего в ролике не должно быть

- Слов «revolutionary», «AI-powered», «100 % safety».
- Выдуманных клиентов и логотипов.
- Сцен с реальными деньгами: в кадре только тестнет и локальные тесты.
