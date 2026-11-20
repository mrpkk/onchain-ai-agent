# Install — ten minutes, no account, no funds

Требуется Python 3.11+ и git. Реальные деньги не нужны: это слой решения, не расчётный рельс.

> **Проверено 26.10.2026 на чистом клоне:** `git clone → venv → pip install → uvicorn` →
> `/health` 200, конверт создаётся, первый расход даёт `ALLOW` с подписанной квитанцией
> (`signed: true`, Ed25519), три атаки отказаны. Заняло меньше пяти минут без кеша.

## 1. Код и зависимости

```bash
git clone https://github.com/mrpkk/onchain-ai-agent.git
cd onchain-ai-agent
git checkout feature/v2-modernization
cd backend
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
```

## 2. Запуск демо и API

```bash
.venv/bin/python -m uvicorn src.demo.app:app --host 127.0.0.1 --port 8295
```

Проверка (в другом терминале):

```bash
curl -s http://127.0.0.1:8295/health
# {"status":"ok","service":"karta-demo","scenarios":4,...}
```

Открой <http://127.0.0.1:8295/> — четыре сценария, вердикт выдаёт тот же движок, что и API.

## 3. Первый конверт и первый расход

```bash
EID=$(curl -s -X POST http://127.0.0.1:8295/api/v1/envelopes \
  -H 'content-type: application/json' \
  -d '{"budget_total":"2.50","per_call_max":"0.05","calls_max":2000,
       "allowlist":["api.example.com"],"ttl_hours":2}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["envelope_id"])')

curl -s -X POST "http://127.0.0.1:8295/api/v1/envelopes/$EID/spend" \
  -H 'content-type: application/json' \
  -d '{"amount":"0.05","payee":"api.example.com"}'
```

Ответ содержит `verdict` и `receipt` с подписью Ed25519. Пятьдесят первый платёж того же
размера при бюджете `2.50` получит `BLOCK / E06` — это и есть граница задачи.

## 4. Атаки (проверка, что защита не декоративная)

```bash
cd ..   # корень репозитория
python3 attacks/runaway_loop.py
python3 attacks/prompt_injection_payee.py
python3 attacks/tool_poisoning_amount.py
```

Каждый скрипт выходит `0`, если атака отказана. Если хоть один выйдет `1` — не устанавливайте,
сначала напишите нам: политику сломали.

## 5. Остановка и доказательство

```bash
# остановить всё немедленно
curl -s -X POST http://127.0.0.1:8295/api/v1/kill -H 'content-type: application/json' -d '{"active":true,"reason":"drill"}'

# пакет доказательств (проверяется офлайн)
curl -s http://127.0.0.1:8295/api/v1/evidence > /tmp/bundle.json
python3 scripts/verify_evidence.py /tmp/bundle.json   # exit 0 = цепочка целая

# снять остановку
curl -s -X POST http://127.0.0.1:8295/api/v1/kill -H 'content-type: application/json' -d '{"active":false}'
```

## 6. Где что лежит

| Что | Путь |
|---|---|
| Конверт и правила E01–E07 | `backend/src/security/envelope.py` |
| Бюджет (атомарный резерв) | `backend/src/security/ledger.py` |
| Kill-switch | `backend/src/security/killswitch.py` |
| Пакеты и подписи | `backend/src/security/evidence.py` |
| x402-разбор | `backend/src/security/x402.py` |
| Демо и API | `backend/src/demo/app.py` |

Данные локальные: SQLite в `~/.local/share/karta-demo/`, ключ подписи — в `~/.config/karta/`.
Ничего не уходит на наши серверы.

## Если что-то не так

Открой issue в репозитории с выводом команды и версией Python. Мы отвечаем честно, включая
случаи «это не работает».
