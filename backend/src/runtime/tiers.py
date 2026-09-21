"""Trust-тиры KARTA (SPEC S4-04): режимы и шаблоны политик.

Tier 0 Demo (виртуальные) → 1 Simulated (read-only) → 2 Limited Live → 3 Full.
Реальное исполнение (тиры 2–3) остаётся за STOP-GATE Phase 5: тир влияет на
simulation_mode и шаблон Dharma-политики, но не отменяет гейты ядра.
"""

from __future__ import annotations

TIER_NAMES = {0: "demo", 1: "simulated", 2: "limited_live", 3: "full"}

TIER_DESCRIPTIONS = {
    0: "Demo — виртуальные средства, безопасные эксперименты",
    1: "Simulated — реальные данные, исполнение отключено",
    2: "Limited Live — малые лимиты, обязательные подтверждения",
    3: "Full — расширенные лимиты (после ревью)",
}

TIER_LIMITS = {  # (per_tx_eth, daily_eth)
    0: (0.1, 0.5),
    1: (0.5, 2.0),
    2: (0.1, 0.5),
    3: (1.0, 5.0),
}

TIER_POLICY_TEMPLATES: dict[int, str] = {
    0: """
version: 1
limits:
  per_tx_eth: 0.1
  daily_eth: 0.5
deny:
  actions: [deploy]
approvals:
  required_if: {risk_score_gte: 0.6, amount_eth_gte: 0.1, new_spender: true}
""",
    1: """
version: 1
limits:
  per_tx_eth: 0.5
  daily_eth: 2.0
deny:
  actions: [deploy]
approvals:
  required_if: {risk_score_gte: 0.6, amount_eth_gte: 0.3, new_spender: true}
""",
    2: """
version: 1
limits:
  per_tx_eth: 0.1
  daily_eth: 0.5
deny:
  actions: [deploy]
approvals:
  required_if: {risk_score_gte: 0.5, amount_eth_gte: 0.05, new_spender: true}
undo:
  window_seconds: 300
  threshold_eth: 0.05
""",
    3: """
version: 1
limits:
  per_tx_eth: 1.0
  daily_eth: 5.0
deny:
  actions: [deploy]
approvals:
  required_if: {risk_score_gte: 0.5, amount_eth_gte: 0.25, new_spender: true}
undo:
  window_seconds: 120
  threshold_eth: 0.25
""",
}


def tier_simulation_mode(tier: int) -> bool:
    """Тиры 0–1 — только симуляция; 2–3 допускают исполнение (за гейтами)."""
    return int(tier) < 2


def tier_default_limits(tier: int) -> tuple[float, float]:
    return TIER_LIMITS.get(int(tier), TIER_LIMITS[0])


def tier_policy_template(tier: int) -> str:
    return TIER_POLICY_TEMPLATES.get(int(tier), TIER_POLICY_TEMPLATES[0])


TRUST_LADDER = ["observe", "suggest", "simulate", "approve", "limited_auto", "autonomous"]


def trust_ladder_rung(tier: int, *, simulation_mode: bool = True,
                      undo_window_seconds: int = 0,
                      approvals_amount_eth: float = 0.0) -> dict:
    """Текущая ступень доверия (наблюдаемая, без авто-изменений).

    Маппинг честный и консервативный:
      tier 0-1 → simulate (исполнение выключено)
      tier 2  → approve (если есть окно undo/порог аппрува) иначе limited_auto
      tier 3  → autonomous (если окно undo выключено) иначе limited_auto
    """
    if int(tier) <= 1 or simulation_mode:
        rung = "simulate"
    elif int(tier) == 2:
        rung = "approve" if (undo_window_seconds > 0 or approvals_amount_eth > 0) else "limited_auto"
    else:
        rung = "autonomous" if undo_window_seconds == 0 else "limited_auto"
    return {
        "rung": rung,
        "rung_index": TRUST_LADDER.index(rung),
        "ladder": TRUST_LADDER,
        "tier": int(tier),
    }
