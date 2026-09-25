"""KARTA MCP-сервер (S6-04): read-only tools, local-first, streamable HTTP.

См. `contracts.py` — канон-контракты tools; `server.py` — реализация.
"""

from .contracts import READ_TOOLS, WRITE_TOOLS_GATED, tool_contracts_markdown

__all__ = ["READ_TOOLS", "WRITE_TOOLS_GATED", "tool_contracts_markdown"]
