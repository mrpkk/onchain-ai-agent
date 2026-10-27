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

from mcp.types import ToolAnnotations

from ..security import killswitch, ledger
from ..security.envelope import Envelope, SpendRequest, evaluate

PUBLIC_TOOL = "check_spend"
MAX_ENVELOPES_PER_HOUR = 30
_created: list[float] = []  # простой предохранитель от мусора в публичном ledger


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
    title="Check a spend against a task envelope",
    description=(
        "Check whether a proposed agent spend is inside a task envelope. "
        "Returns verdict, rule, reason, counterfactual and next. No state is stored."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False),
)
async def check_spend(
    envelope: dict[str, Any],
    amount: str,
    payee: str,
    calls_so_far: int = 0,
    spent_so_far: str = "0",
    is_subscription: bool = False,
) -> str:
    if killswitch.is_active():
        return json.dumps({
            "error": {"code": "KILL_SWITCH", "message": "KARTA is stopped by the operator",
                      "retryable": True,
                      "suggested_action": "retry after the operator resumes the service"},
        }, ensure_ascii=False)
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


def _guard() -> str | None:
    if killswitch.is_active():
        return json.dumps({"error": {"code": "KILL_SWITCH",
                                     "message": "KARTA is stopped by the operator",
                                     "retryable": True,
                                     "suggested_action": "retry after the operator resumes"}})
    return None


@mcp.tool(
    name="open_envelope",
    title="Open a task envelope",
    description=(
        "Create a signed budget envelope for one task: total budget, per-call cap, call count, "
        "allowlisted payees, subscription rule, expiry. Stores it in this server's local ledger "
        "(no funds move, no keys). Returns the envelope id. Capped at 30 envelopes/hour per server."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                idempotentHint=False, openWorldHint=False),
)
async def open_envelope(
    budget_total: str,
    per_call_max: str,
    calls_max: int,
    allowlist: list[str] | None = None,
    allow_subscriptions: bool = False,
    allow_new_payee: bool = False,
    approval_threshold: str | None = None,
    ttl_hours: int = 24,
) -> str:
    stopped = _guard()
    if stopped:
        return stopped
    now = datetime.now().timestamp()
    _created[:] = [t for t in _created if now - t < 3600]
    if len(_created) >= MAX_ENVELOPES_PER_HOUR:
        return json.dumps({"error": {"code": "RATE_LIMITED",
                                     "message": "too many envelopes created this hour",
                                     "retryable": True,
                                     "suggested_action": "try later or run KARTA locally"}})
    try:
        item = ledger.create(
            budget_total=_decimal(budget_total, "budget_total"),
            per_call_max=_decimal(per_call_max, "per_call_max"),
            calls_max=int(calls_max),
            allowlist=tuple(str(a).lower() for a in (allowlist or [])),
            allow_new_payee=bool(allow_new_payee),
            allow_subscriptions=bool(allow_subscriptions),
            approval_threshold=(_decimal(approval_threshold, "approval_threshold")
                                if approval_threshold else None),
            ttl_hours=max(1, min(int(ttl_hours), 168)),
        )
    except (TypeError, ValueError) as exc:
        return json.dumps({"error": {"code": "INVALID_INPUT", "message": str(exc),
                                     "retryable": False,
                                     "suggested_action": "send decimals as strings"}})
    _created.append(now)
    return json.dumps(item, ensure_ascii=False)


@mcp.tool(
    name="get_envelope",
    title="Read an envelope",
    description=(
        "Return an envelope's state: budget, per-call cap, calls used, spent, remaining, allowlist "
        "and expiry. Read-only."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False),
)
async def get_envelope(envelope_id: str) -> str:
    item = ledger.get(envelope_id)
    if item is None:
        return json.dumps({"error": {"code": "NOT_FOUND", "message": "envelope not found",
                                     "retryable": False, "suggested_action": "open_envelope"}})
    return json.dumps(item, ensure_ascii=False)


@mcp.tool(
    name="kill_envelope",
    title="Stop an envelope",
    description=(
        "Stop one task envelope immediately: no further spend is approved for it, the reason is "
        "recorded with a timestamp. Idempotent — the first reason wins."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                idempotentHint=True, openWorldHint=False),
)
async def kill_envelope(envelope_id: str, reason: str = "owner stop") -> str:
    stopped = _guard()
    if stopped:
        return stopped
    pack = ledger.kill(envelope_id, reason=reason)
    if pack is None:
        return json.dumps({"error": {"code": "NOT_FOUND", "message": "envelope not found",
                                     "retryable": False, "suggested_action": "open_envelope"}})
    return json.dumps({"stopped": True, "envelope_id": envelope_id,
                       "kill": pack.get("kill"), "spent": pack.get("totals", {}).get("spent")},
                      ensure_ascii=False)


@mcp.tool(
    name="envelope_evidence",
    title="Evidence pack for an envelope",
    description=(
        "Return an evidence bundle for one envelope: state, every recorded spend, the stop record "
        "and a sha256 of the whole pack that anyone can recompute. Read-only."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False),
)
async def envelope_evidence(envelope_id: str) -> str:
    pack = ledger.evidence(envelope_id)
    if pack is None:
        return json.dumps({"error": {"code": "NOT_FOUND", "message": "envelope not found",
                                     "retryable": False, "suggested_action": "open_envelope"}})
    return json.dumps(pack, ensure_ascii=False)


@mcp.tool(
    name="policy_rules",
    title="List policy rules",
    description=(
        "List the deterministic rules a spend is checked against (E01-E08) with the order they are "
        "applied and the meaning of each. Read-only, no state."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                idempotentHint=True, openWorldHint=False),
)
async def policy_rules() -> str:
    rules = [
        {"rule": "E01", "code": "envelope_expired", "when": "now >= expiry"},
        {"rule": "E02", "code": "subscription_not_permitted", "when": "recurring charge while subscriptions are off"},
        {"rule": "E03", "code": "payee_not_allowed", "when": "payee is not in the allowlist"},
        {"rule": "E04", "code": "per_call_exceeded", "when": "amount > per-call cap"},
        {"rule": "E05", "code": "calls_exhausted", "when": "call count reached"},
        {"rule": "E06", "code": "budget_exceeded", "when": "spent + amount > budget"},
        {"rule": "E07", "code": "above_approval_threshold", "when": "amount >= threshold (verdict HOLD)"},
        {"rule": "E08", "code": "envelope_killed", "when": "envelope was stopped"},
    ]
    return json.dumps({"rules": rules, "order": "applied in the listed order, first match wins",
                       "verdicts": ["ALLOW", "HOLD", "BLOCK"]}, ensure_ascii=False)


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
                allowed_hosts=["localhost", "127.0.0.1", "testserver", "rta.lat", "karta.rta.lat"],
                allowed_origins=[
                    "http://localhost", "http://127.0.0.1", "http://testserver",
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
