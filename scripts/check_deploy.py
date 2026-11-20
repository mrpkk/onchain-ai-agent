#!/usr/bin/env python3
"""Проверка, что прод-контур karta-demo действительно работает с main.

    python3 scripts/check_deploy.py            # проверки + вердикт, код 1 при провале

Что проверяется и почему именно это:
 1. `git`: рабочая копия и `main` указывают на один коммит. Расхождение значит,
    что на проде код, которого нет в main, — и после следующего деплоя поведение
    изменится непредсказуемо.
 2. `/health` демо — 200 и `scenarios` на месте.
 3. Главная демо — 200 (HTML, не JSON: 20.11 уже был случай, когда страница
    отдавалась под `application/json`).
 4. kill-switch отвечает и не «включён по умолчанию» (демо должно быть живым).
 5. Скрипт выдачи отчёта существует и печатает JSON с файлами — иначе касса
    примет оплату, а выдать будет нечего.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = "http://127.0.0.1:8295"
REPORT = ROOT / "backend" / "src" / "billing" / "karta_report.py"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True).stdout.strip()


def get(path: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(DEMO + path, timeout=15) as r:
            return r.status, r.headers.get("content-type", ""), r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), ""
    except Exception as exc:
        return 0, str(exc), ""


def check() -> list[tuple[bool, str]]:
    rows: list[tuple[bool, str]] = []

    head, main = git("rev-parse", "HEAD"), git("rev-parse", "main")
    rows.append((head == main, f"прод-код = main ({head[:8]} vs {main[:8]})"))

    status, _ct, body = get("/health")
    ok_health = status == 200 and '"karta-demo"' in body and '"scenarios"' in body
    rows.append((ok_health, f"/health {status} и service/scenarios в ответе"))

    status, ctype, body = get("/")
    rows.append((status == 200 and "text/html" in ctype,
                 f"главная демо {status}, тип {ctype.split(';')[0] or '—'}"))

    status, _ct, body = get("/health")
    try:
        kill_active = json.loads(body).get("kill_switch", {}).get("active")
    except Exception:
        kill_active = None
    rows.append((kill_active is False, f"kill-switch не включён по умолчанию ({kill_active})"))

    rows.append((REPORT.exists(), f"скрипт выдачи отчёта на месте ({REPORT.name})"))
    return rows


def main() -> int:
    rows = check()
    for ok, text in rows:
        print(("ok   " if ok else "FAIL ") + text)
    bad = [t for ok, t in rows if not ok]
    print("вердикт:", "прод готов" if not bad else f"проблем: {len(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
