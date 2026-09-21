"""Сборка runtime-агента из записи БД (SPEC S3-06: интеграция API⟷Runtime).

Агент собирается из: агент-строки (agents), активной Dharma-политики (policies),
KeyVault (ключ кошелька), Sakshi Log, WS event_sink. Если политики нет —
дефолтная консервативная; если vault/audit-ключ не настроены — агент работает
в режиме без исполнения (честный fail-safe).
"""

from __future__ import annotations

import logging
from typing import Optional

from ..agent.core import AgentConfig, OnChainAgent
from ..db import PolicyRepository, session_scope
from ..security.dharma import build_default_policy, compile_yaml
from ..security.keyvault import KeyVault, master_key_from_env
from ..security.sakshi import AuditKeyMissing, SakshiLog
from .tiers import tier_default_limits, tier_policy_template, tier_simulation_mode

logger = logging.getLogger("runtime.factory")

CHAIN_NAMES = {1: "ethereum", 56: "bsc", 137: "polygon", 11155111: "sepolia"}


async def build_agent(agent_row, *, event_sink=None,
                      vault: Optional[KeyVault] = None,
                      sakshi: Optional[SakshiLog] = None,
                      notifier=None) -> OnChainAgent:
    """Собирает OnChainAgent для записи агента из БД."""
    async with session_scope() as session:
        policy_row = await PolicyRepository(session).get_active(agent_row.id)

    tier = int(getattr(agent_row, "tier", 0) or 0)
    if policy_row is not None:
        policy = compile_yaml(policy_row.dsl_yaml)
    else:
        per_tx, daily = tier_default_limits(tier)
        policy = build_default_policy(per_tx_eth=per_tx, daily_eth=daily)

    if vault is None:
        try:
            vault = KeyVault(master_key_from_env())
        except RuntimeError as e:
            logger.warning("Runtime: KeyVault недоступен (%s) — без кошелька", e)
            vault = None

    if sakshi is None:
        try:
            sakshi = SakshiLog()
        except AuditKeyMissing as e:
            logger.warning("Runtime: Sakshi недоступен (%s) — аудит только в память", e)
            sakshi = None

    if notifier is None:
        try:
            from ..integrations.telegram import notifier_from_env
            notifier = notifier_from_env()
        except Exception as e:  # noqa: BLE001
            logger.warning("Runtime: Telegram notifier недоступен (%s)", e)
            notifier = None

    config = AgentConfig(
        name=agent_row.name,
        chain=CHAIN_NAMES.get(agent_row.chain_id, "ethereum"),
        simulation_mode=tier_simulation_mode(tier),
    )
    return OnChainAgent(
        config,
        vault=vault,
        policy=policy,
        db_agent_id=agent_row.id,
        sakshi=sakshi,
        event_sink=event_sink,
        notifier=notifier.send_approval if notifier is not None else None,
    )
