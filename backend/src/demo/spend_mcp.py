"""Public, stateless `check_spend` MCP tool for KARTA (S2b).

Why separate from the authenticated MCP server: the buyer/agent needs a
zero-setup way to ask "does this envelope allow this spend?" without an API
key, a wallet, or a database. The tool only evaluates the envelope supplied in
the request; it never stores, spends, or reads another tenant's data.

Contract: the same `evaluate()` as the demo/API. The response keeps the stable
shape `{verdict, rule, reason, counterfactual, next}`.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from ..security.envelope import Envelope, SpendRequest, evaluate

PUBLIC_TOOL = "check_spend"


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a decimal string") from exc


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("expires_at must be an ISO-8601 string or null")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 string") from exc


def check_spend_payload(
    *,
    envelope: dict[str, Any],
    amount: Any,
    payee: str,
    calls_so_far: int = 0,
    spent_so_far: Any = "0",
    is_subscription: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure, stateless policy check. No network, no DB, no key."""
    if not isinstance(envelope, dict):
        raise ValueError("envelope must be an object")
    allowlist = envelope.get("allowlist") or []
    if not isinstance(allowlist, (list, tuple)) or not all(isinstance(x, str) for x in allowlist):
        raise ValueError("envelope.allowlist must be an array of strings")
    try:
        calls = int(calls_so_far)
    except (TypeError, ValueError) as exc:
        raise ValueError("calls_so_far must be an integer") from exc
    env = Envelope(
        budget_total=_decimal(envelope.get("budget_total"), "budget_total"),
        per_call_max=_decimal(envelope.get("per_call_max"), "per_call_max"),
        calls_max=int(envelope.get("calls_max")),
        allowlist=tuple(allowlist),
        allow_new_payee=bool(envelope.get("allow_new_payee", False)),
        allow_subscriptions=bool(envelope.get("allow_subscriptions", False)),
        approval_threshold=(
            None if envelope.get("approval_threshold") in (None, "")
            else _decimal(envelope.get("approval_threshold"), "approval_threshold")
        ),
        expires_at=_dt(envelope.get("expires_at")),
        envelope_id=str(envelope.get("envelope_id") or ""),
    )
    req = SpendRequest(
        amount=_decimal(amount, "amount"),
        payee=str(payee),
        calls_so_far=calls,
        spent_so_far=_decimal(spent_so_far, "spent_so_far"),
        is_subscription=bool(is_subscription),
        now=now,
    )
    result = evaluate(env, req).to_dict()
    result.update({
        "envelope_id": env.envelope_id,
        "stateless": True,
        "note": "Evaluation only. No payment, no reservation, no data stored.",
    })
    return result


mcp = MCPServer(
    "karta-spend",
    version="0.1.0",
    instructions=(
        "KARTA public spend check: send an envelope and one proposed spend; "
        "get ALLOW/HOLD/BLOCK with the rule. Stateless, no account, no payment."
    ),
)


@mcp.tool(
    name=PUBLIC_TOOL,
    description=(
        "Check whether a proposed agent spend is inside a task envelope. "
        "Returns verdict, rule, reason, counterfactual and next. No state is stored."
    ),
)
async def check_spend(
    envelope: dict[str, Any],
    amount: str,
    payee: str,
    calls_so_far: int = 0,
    spent_so_far: str = "0",
    is_subscription: bool = False,
) -> str:
    try:
        return json.dumps(check_spend_payload(
            envelope=envelope,
            amount=amount,
            payee=payee,
            calls_so_far=calls_so_far,
            spent_so_far=spent_so_far,
            is_subscription=is_subscription,
        ), ensure_ascii=False)
    except (TypeError, ValueError, KeyError) as exc:
        return json.dumps({
            "error": {
                "code": "INVALID_INPUT",
                "message": str(exc),
                "retryable": False,
                "suggested_action": "send a valid envelope and decimal amount",
            }
        }, ensure_ascii=False)


class SpendMCPDispatcher:
    """Stable ASGI mount point; a fresh MCP app per lifespan."""

    def __init__(self) -> None:
        self._app = None

    @asynccontextmanager
    async def lifespan(self):
        app = mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["localhost", "127.0.0.1", "rta.lat", "karta.rta.lat"],
                allowed_origins=[
                    "http://localhost", "http://127.0.0.1",
                    "https://rta.lat", "https://karta.rta.lat",
                ],
            ),
        )
        self._app = app
        try:
            async with app.router.lifespan_context(app):
                yield
        finally:
            self._app = None

    async def __call__(self, scope, receive, send):
        app = self._app
        if app is None:
            raise RuntimeError("spend MCP app is not running (lifespan inactive)")
        scope = dict(scope)
        scope["path"] = "/"
        await app(scope, receive, send)


spend_mcp_dispatcher = SpendMCPDispatcher()
