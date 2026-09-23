"""Бейджи агента (S6-01): on-chain паспорт + KARTA-состояние в одну ленту.

Честно: бейджи не выдумываются — только реальные данные (реестр, health, trust, tier).
UI переводит `id` через i18n (`badge.<id>`), `value` показывается как есть.
"""

from __future__ import annotations

from typing import Optional


def compute_badges(
    *,
    onchain: Optional[dict] = None,
    health: Optional[dict] = None,
    trust: Optional[dict] = None,
    tier: int = 0,
) -> list[dict]:
    badges: list[dict] = []

    if onchain:
        badges.append({
            "id": "onchain",
            "tone": "info",
            "value": f"#{onchain.get('agent_id')}",
        })
        if onchain.get("verified"):
            badges.append({"id": "verified", "tone": "success", "value": None})
        reputation = onchain.get("reputation")
        if reputation is not None:
            tone = "success" if reputation >= 80 else "warning" if reputation >= 50 else "danger"
            badges.append({"id": "reputation", "tone": tone, "value": reputation})

    if health:
        score = health.get("score")
        band = health.get("band")
        tone = "success" if band == "healthy" else "warning" if band == "degraded" else "danger"
        badges.append({"id": "health", "tone": tone, "value": score})

    if trust:
        badges.append({"id": "trust", "tone": "info", "value": trust.get("rung")})

    badges.append({"id": "tier", "tone": "muted", "value": tier})
    return badges
