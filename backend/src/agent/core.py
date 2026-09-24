"""
Agent Core — the main autonomous agent that orchestrates perception, reasoning, planning, and execution.
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from web3 import Web3

from .perception import BlockchainPerception, PriceOracle
from .reasoning import LLMReasoner, RiskAssessor, AgentDecision
from .planning import AgentPlanner, Plan, PlanStatus, StepType
from .gas_oracle import shared_oracle
from .execution import (
    WalletManager, TransactionExecutor, SpendingLimit,
    TransactionResult, TxStatus,
)
from ..db import ApprovalRepository, DecisionRepository, session_scope
from ..security.keyvault import KeyVault
from ..security.sakshi import SakshiLog
from .simulation import SimulationReceipt, SimulationService
from .timelock import PendingAction, TimelockQueue
from ..security.dharma import (
    CompiledPolicy, TxContext, Verdict, VerdictDecision,
    build_default_policy, evaluate as dharma_evaluate,
)

logger = logging.getLogger("agent.core")

AGENT_STATE_DIR = Path(os.getenv("AGENT_STATE_DIR", "~/.onchain-agent/state")).expanduser()


@dataclass
class AgentConfig:
    name: str
    chain: str = "ethereum"
    daily_limit: float = 5.0
    per_tx_limit: float = 1.0
    auto_execute: bool = False
    simulation_mode: bool = True
    ai_model: str = "mistral-small-latest"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.mistral.ai/v1"
    polling_interval: int = 60
    kill_switch: bool = False
    deadman_timeout_seconds: int = 0  # 0 = выключен


@dataclass
class AgentState:
    agent_id: str
    config: AgentConfig
    status: str = "idle"
    current_plan: Optional[Plan] = None
    balance: float = 0.0
    daily_spend: float = 0.0
    total_transactions: int = 0
    successful_transactions: int = 0
    failed_transactions: int = 0
    last_action: Optional[str] = None
    last_action_time: Optional[datetime] = None
    last_simulation: Optional[dict] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.config.name,
            "status": self.status,
            "chain": self.config.chain,
            "balance": self.balance,
            "daily_spend": self.daily_spend,
            "daily_limit": self.config.daily_limit,
            "total_transactions": self.total_transactions,
            "successful_transactions": self.successful_transactions,
            "failed_transactions": self.failed_transactions,
            "last_action": self.last_action,
            "last_action_time": self.last_action_time.isoformat() if self.last_action_time else None,
            "last_simulation": self.last_simulation,
            "kill_switch": self.config.kill_switch,
            "simulation_mode": self.config.simulation_mode,
            "plan_progress": self.current_plan.progress if self.current_plan else 0,
            "created_at": self.created_at.isoformat(),
        }


class OnChainAgent:
    """Autonomous AI agent that operates on EVM blockchains."""

    def __init__(self, config: AgentConfig, vault: Optional[KeyVault] = None,
                 key_alias: str = "agent_wallet",
                 policy: Optional[CompiledPolicy] = None,
                 db_agent_id: Optional[uuid.UUID] = None,
                 sakshi: Optional[SakshiLog] = None,
                 event_sink: Optional[Callable[[dict], Awaitable[None]]] = None,
                 simulator: Optional[SimulationService] = None,
                 notifier: Optional[Callable[[Optional[str], dict], Awaitable[None]]] = None):
        self.config = config
        self.agent_id = f"agent_{config.name.lower().replace(' ', '_')}"

        self.perception = BlockchainPerception([config.chain])
        self.reasoner = LLMReasoner(
            api_key=config.ai_api_key,
            model=config.ai_model,
            base_url=config.ai_base_url,
            agent_id=self.agent_id,
        )
        self.planner = AgentPlanner()
        self.risk_assessor = RiskAssessor()

        self._vault = vault
        self._key_alias = key_alias
        self.wallet: Optional[WalletManager] = None
        self.executor: Optional[TransactionExecutor] = None

        self.policy = policy or build_default_policy(
            per_tx_eth=config.per_tx_limit, daily_eth=config.daily_limit,
        )
        self._dharma_enforce = os.getenv("DHARMA_ENFORCE", "on").strip().lower() not in (
            "off", "0", "false", "no",
        )
        self._execution_times: list[datetime] = []
        self._revert_streak = 0
        self._last_heartbeat: datetime = datetime.now(timezone.utc)
        self._db_agent_id = db_agent_id
        self._sakshi = sakshi
        self._event_sink = event_sink
        self._notifier = notifier
        self.simulator = simulator or SimulationService()
        self.timelock = TimelockQueue()

        self.state = AgentState(
            agent_id=self.agent_id,
            config=config,
        )

        self._running = False
        self._audit_log: list[dict] = []

        AGENT_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _ensure_wallet(self) -> Optional[WalletManager]:
        """Ленивая инициализация кошелька из KeyVault (ключ не хранится в config).

        Возвращает WalletManager или None, если vault не подключён / ключа нет —
        агент продолжает работать без исполнения (fail-safe).
        """
        if self.wallet is not None:
            pass
        elif self._vault is None:
            return None
        else:
            try:
                private_key = self._vault.get_key(self._key_alias)
            except KeyError:
                logger.warning("KeyVault: ключ '%s' не найден — агент без кошелька", self._key_alias)
                return None
            except RuntimeError as e:
                logger.error("KeyVault недоступен: %s", e)
                return None
            self.wallet = WalletManager(private_key, self.config.chain)
            logger.info("Кошелёк инициализирован из KeyVault: %s", self.wallet.address)

        if self.executor is None:
            w3 = self.perception.get_web3(self.config.chain)
            if w3:
                gas_cap_gwei = 0
                try:
                    gas_cap_gwei = int(getattr(self.policy.model.limits, "gas_gwei_cap", 0) or 0)
                except Exception:  # noqa: BLE001 — политика не должна ломать сборку
                    pass
                private_w3 = None
                try:
                    from ..config.settings import get_settings

                    settings = get_settings()
                    if settings.private_rpc_enabled and settings.private_rpc_urls:
                        private_w3 = Web3(Web3.HTTPProvider(
                            settings.private_rpc_urls[0],
                            request_kwargs={"timeout": 15.0},
                        ))
                    jitter_max = float(settings.tx_jitter_max_seconds or 0.0)
                except Exception:  # noqa: BLE001 — настройки не должны ломать сборку
                    jitter_max = 0.0
                self.executor = TransactionExecutor(
                    wallet=self.wallet,
                    w3=w3,
                    spending_limit=SpendingLimit(
                        daily_limit=self.config.daily_limit,
                        per_tx_limit=self.config.per_tx_limit,
                    ),
                    gas_cap_gwei=gas_cap_gwei,
                    private_w3=private_w3,
                    jitter_max_seconds=jitter_max,
                )
        return self.wallet

    _CHAIN_IDS = {"ethereum": 1, "bsc": 56, "polygon": 137, "sepolia": 11155111}
    _RISK_SCORES = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}

    def _policy_gate(self, action: str, params: dict, risk_level: str = "medium",
                     new_spender: bool = False) -> Optional[Verdict]:
        """Дхарма-гейт перед исполнением. None — если enforcement выключен."""
        if not self._dharma_enforce:
            return None
        gas_price = 0.0
        try:
            w3 = self.perception.get_web3(self.config.chain)
            if w3 is not None:
                # S5-04: кап сверяем по реальной EIP-1559-оценке (maxFeePerGas), не по legacy
                gas_price = float(shared_oracle().recommend(w3).max_fee_gwei)
            else:
                gas_price = float(self.perception.get_gas_price(self.config.chain) or 0.0)
        except Exception as e:  # noqa: BLE001
            logger.warning("Dharma: gas price недоступен (%s) — газ-кап пропущен", e)
        ctx = TxContext(
            action=action,
            params=params or {},
            chain_id=self._CHAIN_IDS.get(self.config.chain),
            gas_price_gwei=gas_price,
            spent_today_eth=self.state.daily_spend,
            recent_tx=list(self._execution_times),
            revert_streak=self._revert_streak,
            risk_score=self._RISK_SCORES.get(risk_level, 0.5),
            new_spender=new_spender,
        )
        verdict = dharma_evaluate(self.policy, ctx)
        self._log_audit("policy_verdict", {
            "action": action,
            "decision": verdict.decision.value,
            "reasons": verdict.reasons,
            "rule_ids": verdict.rule_ids,
        })
        return verdict

    def _build_sim_tx(self, action: str, params: dict) -> Optional[dict]:
        """tx-параметры для eth_call (transfer/approve/contract_call)."""
        if self.wallet is None:
            return None
        try:
            sender = self.wallet.address
        except Exception:
            return None
        tx: dict = {"from": sender}
        if action == "transfer":
            to = params.get("to")
            if not to:
                return None
            try:
                tx["to"] = Web3.to_checksum_address(str(to))
            except Exception:
                return None
            amount = float(params.get("amount") or 0)
            tx.update({"value": int(amount * 10**18), "data": "0x"})
        elif action in ("approve", "contract_call"):
            target = params.get("token") or params.get("address")
            if not target:
                return None
            try:
                tx["to"] = Web3.to_checksum_address(str(target))
            except Exception:
                return None
            tx.update({"value": 0, "data": "0x"})
        else:
            return None
        return tx

    def _simulate(self, action: str, params: dict) -> Optional[SimulationReceipt]:
        """Receipt или None, если симуляция невозможна (нет RPC/кошелька/tx-параметров)."""
        w3 = self.perception.get_web3(self.config.chain)
        if w3 is None or self.wallet is None:
            return None
        tx = self._build_sim_tx(action, params)
        if tx is None:
            return None
        return self.simulator.simulate_tx(w3, tx)

    async def _simulation_gate(self, action: str, params: dict) -> Optional[TransactionResult]:
        """None — исполнение разрешено; FAILED-результат — блок (SIMULATION FIRST)."""
        receipt = self._simulate(action, params)
        if receipt is None:
            self._log_audit("simulation_unavailable", {"action": action})
            await self._sakshi_append("simulation_unavailable", {"action": action})
            return TransactionResult(
                tx_hash="", status=TxStatus.FAILED, chain=self.config.chain,
                from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
                error="Simulation unavailable: execution blocked (SIMULATION FIRST)",
            )
        self.state.last_simulation = receipt.to_dict()
        if not receipt.ok or not receipt.is_fresh():
            reason = receipt.revert_reason or "stale simulation receipt"
            self._log_audit("simulation_failed", {"action": action, "reason": reason})
            await self._sakshi_append("simulation_failed", {"action": action, "reason": reason})
            return TransactionResult(
                tx_hash="", status=TxStatus.FAILED, chain=self.config.chain,
                from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
                error=f"Simulation failed: {reason}",
            )
        self._log_audit("simulation_passed", {"action": action,
                                              "gas_estimate": receipt.gas_estimate})
        await self._sakshi_append("simulation_passed", {
            "action": action, "gas_estimate": receipt.gas_estimate,
            "engine": receipt.engine,
        })
        return None

    def _undo_delay(self, action: str, params: dict) -> int:
        """Окно отмены (сек) для действия; 0 — исполнять сразу."""
        if action not in ("transfer", "contract_call", "approve"):
            return 0
        undo = getattr(self.policy.model, "undo", None)
        if undo is None or undo.window_seconds <= 0:
            return 0
        value = float(params.get("amount") or params.get("value") or 0)
        if value < undo.threshold_eth:
            return 0
        return int(undo.window_seconds)

    async def _schedule_with_undo(self, action: str, params: dict,
                                  delay: int) -> TransactionResult:
        pending = self.timelock.schedule(action, params, delay)
        self.state.status = "awaiting_undo"
        self._log_audit("action_scheduled", {"id": pending.id, "action": action,
                                             "execute_after": pending.execute_after.isoformat()})
        await self._sakshi_append("action_scheduled", {
            "id": pending.id, "action": action, "params": params,
            "execute_after": pending.execute_after.isoformat(),
        })
        await self._emit({"type": "action.scheduled",
                          "agent_id": str(self._db_agent_id) if self._db_agent_id else self.agent_id,
                          "id": pending.id, "action": action, "delay_seconds": delay})
        return TransactionResult(
            tx_hash="", status=TxStatus.PENDING, chain=self.config.chain,
            from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
            error=None,
        )

    def heartbeat(self) -> None:
        """Пинг живости от владельца/системы. Продлевает dead-man switch."""
        self._last_heartbeat = datetime.now(timezone.utc)
        self._log_audit("heartbeat", {})

    def _check_deadman(self) -> bool:
        """True и hard-kill, если heartbeat не приходил дольше таймаута."""
        timeout = self.config.deadman_timeout_seconds
        if timeout <= 0:
            return False
        elapsed = (datetime.now(timezone.utc) - self._last_heartbeat).total_seconds()
        if elapsed <= timeout:
            return False
        self._log_audit("deadman_triggered", {"elapsed_seconds": int(elapsed),
                                              "timeout_seconds": timeout})
        self.trigger_kill_switch(mode="hard",
                                 reason=f"dead man switch: no heartbeat for {int(elapsed)}s")
        return True

    def cancel_pending(self, item_id: str) -> bool:
        """Отмена отложенного действия (окно undo)."""
        cancelled = self.timelock.cancel(item_id)
        self._log_audit("action_cancelled", {"id": item_id, "ok": cancelled})
        return cancelled

    async def _process_due_actions(self) -> None:
        """Исполнение действий, у которых истекло окно отмены (полный контур заново)."""
        for item in self.timelock.due():
            if self._kill_switch_active():
                return
            decision = AgentDecision(
                action=item.action, params=item.params,
                reasoning=f"timelock execution (scheduled {item.created_at.isoformat()})",
                confidence=1.0, risk_level="medium",
            )
            result = await self._execute_decision(decision, skip_timelock=True)
            self.timelock.mark(item.id, "executed" if result.status == TxStatus.CONFIRMED else "failed")
            self._log_audit("timelock_executed" if result.status == TxStatus.CONFIRMED
                            else "timelock_failed",
                            {"id": item.id, "status": result.status.value, "error": result.error})
            await self._sakshi_append("timelock_result", {
                "id": item.id, "status": result.status.value, "error": result.error,
            })

    async def execute_intent(self, action: str, params: dict) -> dict:
        """Исполнение подтверждённого намерения из чата (S4-03).

        Проходит весь контур: policy → simulation → timelock → dispatch.
        """
        decision = AgentDecision(
            action=action, params=params or {},
            reasoning="user-confirmed intent via chat (S4-03)",
            confidence=1.0, risk_level="medium",
        )
        result = await self._execute_decision(decision)
        self._update_state_from_result(result)
        return result.to_dict()

    async def _emit(self, event: dict) -> None:
        """Публикация live-события (WS). Ошибки sink не ломают агента."""
        if self._event_sink is None:
            return
        try:
            await self._event_sink(event)
        except Exception as e:
            logger.warning("Event sink error: %s", e)

    async def _sakshi_append(self, event_type: str, payload: dict, actor: str = "agent") -> None:
        """Запись события в Sakshi Log (если подключены БД-агент и аудит)."""
        if self._sakshi is None or self._db_agent_id is None:
            return
        try:
            async with session_scope() as session:
                await self._sakshi.append(session, actor=actor, event_type=event_type,
                                          payload=payload, agent_id=self._db_agent_id)
        except Exception as e:
            logger.error("Sakshi: не удалось записать событие %s: %s", event_type, e)

    async def _persist_decision(self, decision: AgentDecision, verdict=None) -> Optional[str]:
        """Decision Diary: событие в WS + запись решения в decisions.

        Returns: str(id записи) или None (нет БД-агента/ошибка).
        """
        await self._emit({
            "type": "decision.proposed",
            "agent_id": str(self._db_agent_id) if self._db_agent_id else self.agent_id,
            "action": decision.action,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
        })
        if self._db_agent_id is None:
            return None
        try:
            async with session_scope() as session:
                row = await DecisionRepository(session).add(
                    self._db_agent_id,
                    action=decision.action,
                    params=decision.params,
                    reasoning=decision.reasoning,
                    confidence=decision.confidence,
                    risk_level=decision.risk_level,
                    policy_verdict=verdict.to_dict() if verdict is not None else None,
                    requires_approval=decision.requires_approval,
                )
                return str(row.id)
        except Exception as e:
            logger.error("Decision diary: не удалось записать решение: %s", e)
            return None

    async def _raise_approval(self, decision_row_id: Optional[str],
                              decision: AgentDecision) -> None:
        """Создаёт approval-заявку, уведомляет (WS + Telegram) — S4-06."""
        approval_id: Optional[str] = None
        if self._db_agent_id is not None:
            try:
                async with session_scope() as session:
                    row = await ApprovalRepository(session).create(
                        uuid.UUID(decision_row_id) if decision_row_id else None,
                        channel="web", ttl_minutes=30,
                    )
                    approval_id = str(row.id)
            except Exception as e:
                logger.error("Approval: не удалось создать заявку: %s", e)

        self.state.status = "awaiting_approval"
        self._log_audit("approval_requested", {
            "approval_id": approval_id, "action": decision.action,
        })
        await self._sakshi_append("approval_requested", {
            "approval_id": approval_id, "action": decision.action,
            "params": decision.params,
        })
        await self._emit({
            "type": "approval.requested",
            "agent_id": str(self._db_agent_id) if self._db_agent_id else self.agent_id,
            "approval_id": approval_id,
            "action": decision.action,
            "risk_level": decision.risk_level,
        })
        if self._notifier is not None:
            try:
                await self._notifier(approval_id, {
                    "agent": self.config.name,
                    "action": decision.action,
                    "params": decision.params,
                    "reasoning": decision.reasoning or "",
                })
            except Exception as e:
                logger.warning("Approval notifier error: %s", e)

    async def start(self):
        self._running = True
        self.state.status = "running"
        self._log_audit("agent_started", {"config": self.config.name})
        await self._sakshi_append("agent_started", {
            "name": self.config.name, "chain": self.config.chain,
        })
        logger.info(f"Agent '{self.config.name}' started on {self.config.chain}")

        if self._ensure_wallet() is not None:
            w3 = self.perception.get_web3(self.config.chain)
            if w3:
                self.state.balance = self.wallet.get_token_balance(w3, "0x0000000000000000000000000000000000000000")
                if self.state.balance == 0:
                    self.state.balance = float(Web3.from_wei(w3.eth.get_balance(self.wallet.address), "ether"))

        while self._running:
            if self.config.kill_switch:
                logger.warning("Kill switch activated — stopping agent")
                self.state.status = "stopped"
                break

            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Agent tick error: {e}")
                self.state.status = "error"
                self._log_audit("tick_error", {"error": str(e)})
                await self._sakshi_append("tick_error", {"error": str(e)[:300]})

            await asyncio.sleep(self.config.polling_interval)

    async def stop(self):
        self._running = False
        self.state.status = "stopped"
        self._log_audit("agent_stopped", {})
        await self._sakshi_append("agent_stopped", {"name": self.config.name})
        logger.info(f"Agent '{self.config.name}' stopped")

    async def _tick(self):
        self.state.status = "thinking"

        if self._check_deadman():
            return

        await self._process_due_actions()

        if self.state.current_plan and not self.state.current_plan.is_done:
            await self._execute_plan_step()
            return

        if self.state.last_action_time:
            elapsed = (datetime.now(timezone.utc) - self.state.last_action_time).seconds
            if elapsed < self.config.polling_interval:
                return

        state_data = await self._gather_state()
        decision = await self.reasoner.decide(
            state=state_data,
            goal="Monitor the blockchain and take profitable actions within spending limits.",
            history=self._get_recent_actions(),
        )

        decision = self.risk_assessor.assess(
            decision,
            self.state.balance,
            self.state.daily_spend,
        )

        decision_row_id = await self._persist_decision(decision)
        await self._sakshi_append("decision_made", {
            "action": decision.action,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
            "reasoning": (decision.reasoning or "")[:300],
        })

        self._log_audit("decision_made", {
            "action": decision.action,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
            "reasoning": decision.reasoning[:200],
        })

        if decision.action == "ask_human":
            await self._raise_approval(decision_row_id, decision)
            return

        if decision.requires_approval and not self.config.auto_execute:
            await self._raise_approval(decision_row_id, decision)
            return

        if self.config.simulation_mode:
            logger.info(f"SIMULATION: Would execute {decision.action} with params {decision.params}")
            self.state.last_action = f"sim:{decision.action}"
            self.state.last_action_time = datetime.now(timezone.utc)
            return

        result = await self._execute_decision(decision)
        self._update_state_from_result(result)

    async def execute_goal(self, goal: str, chain: str = None) -> Plan:
        chain = chain or self.config.chain
        plan = self.planner.create_plan(goal, {"chain": chain})
        self.state.current_plan = plan
        self.state.status = "executing_plan"
        self._log_audit("plan_created", {"goal": goal, "plan_id": plan.id, "steps": len(plan.steps)})
        return plan

    async def _execute_plan_step(self):
        plan = self.state.current_plan
        if not plan:
            return

        step = plan.get_next_step()
        if not step:
            if plan.is_done:
                plan.status = PlanStatus.COMPLETED
                self.state.status = "idle"
                self._log_audit("plan_completed", {"plan_id": plan.id})
            return

        step.status = PlanStatus.IN_PROGRESS
        logger.info(f"Executing step: {step.description}")

        try:
            if self._kill_switch_active():
                step.status = PlanStatus.FAILED
                step.error = "Kill switch active: execution blocked"
                self._log_audit("kill_switch_block", {"step_id": step.id})
                return

            if step.step_type in (StepType.TRANSFER, StepType.CONTRACT_CALL, StepType.APPROVE):
                verdict = self._policy_gate(step.step_type.value, step.params)
                if verdict is not None:
                    if verdict.decision == VerdictDecision.DENY:
                        step.status = PlanStatus.FAILED
                        step.error = "Policy denied: " + "; ".join(verdict.reasons)
                        self._log_audit("policy_denied", {"step_id": step.id, "reasons": verdict.reasons})
                        return
                    if verdict.decision == VerdictDecision.REQUIRE_APPROVAL:
                        step.status = PlanStatus.BLOCKED
                        step.error = "Policy requires approval: " + "; ".join(verdict.reasons)
                        self.state.status = "awaiting_approval"
                        self._log_audit("policy_require_approval", {"step_id": step.id, "reasons": verdict.reasons})
                        return
                self._ensure_wallet()
                if self.executor is None:
                    raise RuntimeError("Кошелёк не настроен (KeyVault): шаг требует исполнения")
                blocked = await self._simulation_gate(step.step_type.value, step.params)
                if blocked is not None:
                    step.status = PlanStatus.FAILED
                    step.error = blocked.error
                    return

            if step.step_type == StepType.READ_STATE:
                state = await self._gather_state()
                step.result = state
                step.status = PlanStatus.COMPLETED

            elif step.step_type == StepType.TRANSFER:
                result = await asyncio.to_thread(
                    self.executor.send_eth,
                    to_address=step.params.get("to", ""),
                    amount_eth=step.params.get("amount", 0),
                    chain=step.chain,
                )
                step.result = result.to_dict()
                step.status = PlanStatus.COMPLETED if result.status == TxStatus.CONFIRMED else PlanStatus.FAILED

            elif step.step_type == StepType.CONTRACT_CALL:
                result = self.executor.call_contract(
                    contract_address=step.params.get("address", ""),
                    abi=step.params.get("abi", []),
                    function_name=step.params.get("function", ""),
                    args=step.params.get("args", []),
                    value_eth=step.params.get("value", 0),
                    chain=step.chain,
                )
                step.result = result.to_dict()
                step.status = PlanStatus.COMPLETED if result.status == TxStatus.CONFIRMED else PlanStatus.FAILED

            elif step.step_type == StepType.APPROVE:
                result = self.executor.approve_token(
                    token_address=step.params.get("token", ""),
                    spender=step.params.get("spender", ""),
                    amount=step.params.get("amount"),
                    chain=step.chain,
                )
                step.result = result.to_dict()
                step.status = PlanStatus.COMPLETED if result.status == TxStatus.CONFIRMED else PlanStatus.FAILED

            elif step.step_type == StepType.WAIT:
                step.status = PlanStatus.COMPLETED

            elif step.step_type == StepType.CONDITIONAL:
                step.status = PlanStatus.COMPLETED

            else:
                step.status = PlanStatus.COMPLETED

        except Exception as e:
            step.error = str(e)
            step.status = PlanStatus.FAILED
            logger.error(f"Step failed: {e}")

        if step.step_type in (StepType.TRANSFER, StepType.CONTRACT_CALL, StepType.APPROVE):
            self._execution_times.append(datetime.now(timezone.utc))
            if step.status == PlanStatus.COMPLETED:
                self._revert_streak = 0
            elif step.status == PlanStatus.FAILED:
                self._revert_streak += 1

        self._log_audit("step_executed", {
            "step_id": step.id,
            "type": step.step_type.value,
            "status": step.status.value,
        })

    def trigger_kill_switch(self, mode: str = "hard", reason: str = "") -> None:
        """Soft — пауза новых действий; hard — терминальная остановка без auto-resume."""
        self.state.status = "killed" if mode == "hard" else "paused"
        if mode == "hard":
            self.config.kill_switch = True
        self._log_audit("kill_switch", {"mode": mode, "reason": reason})

    def _kill_switch_active(self) -> bool:
        return self.config.kill_switch or self.state.status in ("killed", "paused")

    async def _execute_decision(self, decision: AgentDecision, *,
                                skip_timelock: bool = False) -> TransactionResult:
        if self._kill_switch_active():
            self._log_audit("kill_switch_block", {"action": decision.action})
            return TransactionResult(
                tx_hash="", status=TxStatus.FAILED, chain=self.config.chain,
                from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
                error="Kill switch active: execution blocked",
            )
        if decision.action in ("transfer", "contract_call", "approve"):
            verdict = self._policy_gate(decision.action, decision.params,
                                        risk_level=decision.risk_level)
            if verdict is not None:
                await self._sakshi_append("policy_verdict", {
                    "action": decision.action, **verdict.to_dict(),
                })
            if verdict is not None and verdict.decision != VerdictDecision.ALLOW:
                self._log_audit(f"policy_{verdict.decision.value}", {
                    "action": decision.action, "reasons": verdict.reasons,
                })
                if verdict.decision == VerdictDecision.REQUIRE_APPROVAL:
                    self.state.status = "awaiting_approval"
                return TransactionResult(
                    tx_hash="", status=TxStatus.FAILED, chain=self.config.chain,
                    from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
                    error=f"Policy {verdict.decision.value}: " + "; ".join(verdict.reasons),
                )
        self._ensure_wallet()
        if decision.action in ("transfer", "contract_call", "approve") and self.executor is None:
            return TransactionResult(
                tx_hash="", status=TxStatus.FAILED, chain=self.config.chain,
                from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
                error="Wallet not configured (KeyVault): execution unavailable",
            )
        if decision.action in ("transfer", "contract_call", "approve"):
            blocked = await self._simulation_gate(decision.action, decision.params)
            if blocked is not None:
                return blocked
            if not skip_timelock:
                delay = self._undo_delay(decision.action, decision.params)
                if delay > 0:
                    return await self._schedule_with_undo(decision.action,
                                                          decision.params, delay)
        if decision.action == "transfer":
            return self.executor.send_eth(
                to_address=decision.params.get("to", ""),
                amount_eth=decision.params.get("amount", 0),
                chain=self.config.chain,
            )
        elif decision.action == "contract_call":
            return self.executor.call_contract(
                contract_address=decision.params.get("address", ""),
                abi=decision.params.get("abi", []),
                function_name=decision.params.get("function", ""),
                args=decision.params.get("args", []),
                value_eth=decision.params.get("value", 0),
                chain=self.config.chain,
            )
        elif decision.action == "approve":
            return self.executor.approve_token(
                token_address=decision.params.get("token", ""),
                spender=decision.params.get("spender", ""),
                amount=decision.params.get("amount"),
                chain=self.config.chain,
            )
        elif decision.action == "hold":
            self.state.last_action = "hold"
            self.state.last_action_time = datetime.now(timezone.utc)
            return TransactionResult(
                tx_hash="hold", status=TxStatus.CONFIRMED, chain=self.config.chain,
                from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
            )
        else:
            return TransactionResult(
                tx_hash="", status=TxStatus.FAILED, chain=self.config.chain,
                from_address="", to_address="", value=0, gas_used=0, gas_price_gwei=0,
                error=f"Unknown action: {decision.action}",
            )

    async def _gather_state(self) -> dict:
        state = {
            "agent": self.state.to_dict(),
            "chain": self.config.chain,
            "block_number": self.perception.get_block_number(self.config.chain),
            "gas_price_gwei": self.perception.get_gas_price(self.config.chain),
        }

        oracle = PriceOracle()
        prices = await oracle.get_price()
        state["prices"] = {k: v.price_usd for k, v in prices.items()}

        if self._ensure_wallet():
            w3 = self.perception.get_web3(self.config.chain)
            if w3:
                state["wallet"] = {
                    "address": self.wallet.address,
                    "balance_eth": float(Web3.from_wei(
                        w3.eth.get_balance(Web3.to_checksum_address(self.wallet.address)),
                        "ether"
                    )),
                }

        return state

    def _update_state_from_result(self, result: TransactionResult):
        if result.status == TxStatus.PENDING:
            self.state.last_action = "scheduled"
            self.state.last_action_time = datetime.now(timezone.utc)
            return
        self.state.total_transactions += 1
        if result.status == TxStatus.CONFIRMED:
            self.state.successful_transactions += 1
            self._revert_streak = 0
            if result.value > 0:
                self.state.daily_spend += result.value
        else:
            self.state.failed_transactions += 1
            if result.status in (TxStatus.REVERTED, TxStatus.FAILED):
                self._revert_streak += 1
        self._execution_times.append(datetime.now(timezone.utc))
        self.state.last_action = f"{result.status.value}:{result.tx_hash[:10]}"
        self.state.last_action_time = datetime.now(timezone.utc)
        self.state.status = "running"

    def _get_recent_actions(self) -> list[dict]:
        return self._audit_log[-20:]

    def _log_audit(self, event: str, data: dict):
        entry = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]

    def save_state(self):
        state_file = AGENT_STATE_DIR / f"{self.agent_id}.json"
        state_file.write_text(json.dumps(self.state.to_dict(), indent=2, default=str))

    def load_state(self):
        state_file = AGENT_STATE_DIR / f"{self.agent_id}.json"
        if state_file.exists():
            data = json.loads(state_file.read_text())
            self.state.balance = data.get("balance", 0)
            self.state.total_transactions = data.get("total_transactions", 0)
            self.state.successful_transactions = data.get("successful_transactions", 0)
            self.state.failed_transactions = data.get("failed_transactions", 0)
