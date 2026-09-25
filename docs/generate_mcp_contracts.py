#!/usr/bin/env python3
"""Генерация docs/MCP_TOOL_CONTRACTS.md из backend/src/mcp/contracts.py.

Запуск (из корня репозитория):
    backend/.venv/bin/python docs/generate_mcp_contracts.py
После изменения контрактов — перегенерировать и закоммитить (parity-тест в test_mcp.py).
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.mcp.contracts import tool_contracts_markdown  # noqa: E402


def main() -> None:
    out = ROOT / "docs" / "MCP_TOOL_CONTRACTS.md"
    out.write_text(tool_contracts_markdown() + "\n", encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    main()
