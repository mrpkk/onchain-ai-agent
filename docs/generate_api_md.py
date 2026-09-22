#!/usr/bin/env python3
"""Генерация docs/API.md из OpenAPI-схемы приложения.

Запуск (из корня репозитория):
    DEBUG=true backend/.venv/bin/python docs/generate_api_md.py

Пишет docs/API.md: сводка по тегам, все роуты (метод/путь/summary/коды),
заметки о безопасности (JWT/ownership). Скрипт — источник истины для API.md:
после изменения роутов перегенерировать и закоммитить.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.api.main import app  # noqa: E402

METHODS = ["get", "post", "put", "patch", "delete"]


def main() -> None:
    spec = app.openapi()
    paths = spec["paths"]

    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in sorted(paths.items()):
        for method, op in ops.items():
            if method not in METHODS:
                continue
            tag = (op.get("tags") or ["/"])[0]
            by_tag.setdefault(tag, []).append((method, path, op))

    lines: list[str] = [
        "# KARTA API",
        "",
        "> AUTO-GENERATED: `docs/generate_api_md.py` (источник — OpenAPI приложения).",
        f"> Роутов: **{sum(len(v) for v in by_tag.values())}** · тегов: **{len(by_tag)}**. SwaggerUI: `/docs`.",
        "",
        "## Безопасность",
        "",
        "- Почти все приватные роуты требуют `Authorization: Bearer <access_token>` (JWT, HS256; refresh с ротацией и reuse-detection).",
        "- Все агентские ресурсы проверяют **ownership** (агент принадлежит текущему пользователю) → чужие id дают 404.",
        "- Approvals приходят из двух транспортов (web/TG) в **единый** `resolve_approval` → полный контур policy→simulation→timelock.",
        "- Аудит (Sakshi Log) — HMAC-цепочка; экспорт CSV включает хвост hash-цепочки.",
        "",
    ]

    for tag in sorted(by_tag):
        lines.append(f"## {tag}")
        lines.append("")
        lines.append("| Метод | Путь | Назначение | Ответы |")
        lines.append("|---|---|---|---|")
        for method, path, op in by_tag[tag]:
            summary = (op.get("summary") or op.get("operationId") or "").replace("|", "/")
            codes = ", ".join(sorted((op.get("responses") or {}).keys()))
            lines.append(f"| `{method.upper()}` | `{path}` | {summary} | {codes} |")
        lines.append("")

    out = ROOT / "docs" / "API.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {out} ({len(lines)} lines, {sum(len(v) for v in by_tag.values())} routes)")


if __name__ == "__main__":
    main()
