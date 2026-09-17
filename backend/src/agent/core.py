"""
Agent Core — the main autonomous agent that orchestrates perception, reasoning, planning, and execution.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from web3 import Web3

from .perception import BlockchainPerception, PriceOracle
from .reasoning import LLMReasoner, RiskAssessor, AgentDecision
from .planning import AgentPlanner, Plan, PlanStatus, StepType
from .execution import (
    WalletManager, TransactionExecutor, SpendingLimit,
    TransactionResult, TxStatus,
)
from ..security.keyvault import KeyVault
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
            "kill_switch": self.config.kill_switch,
            "simulation_mode": self.config.simulation_mode,
            "plan_progress": self.current_plan.progress if self.current_plan else 0,
            "created_at": self.created_at.isoformat(),
        }


class OnChainAgent:
    """Autonomous AI agent that operates on EVM blockchains."""

    def __init__(self, config: AgentConfig, vault: Optional[KeyVault] = None,
                 key_alias: str = "agent_wallet",
                 policy: Optional[CompiledPolicy] = None):
        self.config = config
        self.agent_id = f"agent_{config.name.lower().replace(' ', '_')}"

        self.perception = BlockchainPerception([config.chain])
        self.reasoner = LLMReasoner(
            api_key=config.ai_api_key,
            model=config.ai_model,
            base_url=config.ai_base_url,
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
                self.executor = TransactionExecutor(
                    wallet=self.wallet,
                    w3=w3,
                    spending_limit=SpendingLimit(
                        daily_limit=self.config.daily_limit,
                        per_tx_limit=self.config.per_tx_limit,
                    ),
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
            gas_price = float(self.perception.get_gas_price(self.config.chain) or 0.0)
        except Exception as e:
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

    async def start(self):
        self._running = True
        self.state.status = "running"
        self._log_audit("agent_started", {"config": self.config.name})
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

            await asyncio.sleep(self.config.polling_interval)

    async def stop(self):
        self._running = False
        self.state.status = "stopped"
        self._log_audit("agent_stopped", {})
        logger.info(f"Agent '{self.config.name}' stopped")

    async def _tick(self):
        self.state.status = "thinking"

        if self.current_plan and not self.current_plan.is_done:
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

        self._log_audit("decision_made", {
            "action": decision.action,
            "confidence": decision.confidence,
            "risk_level": decision.risk_level,
            "reasoning": decision.reasoning[:200],
        })

        if decision.action == "ask_human":
            self.state.status = "awaiting_approval"
            self._log_audit("awaiting_approval", decision.params)
            return

        if decision.requires_approval and not self.config.auto_execute:
            self.state.status = "awaiting_approval"
            self._log_audit("requires_approval", {
                "action": decision.action,
                "params": decision.params,
            })
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

            if step.step_type == StepType.READ_STATE:
                state = await self._gather_state()
                step.result = state
                step.status = PlanStatus.COMPLETED

            elif step.step_type == StepType.TRANSFER:
                result = self.executor.send_eth(
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

    async def _execute_decision(self, decision: AgentDecision) -> TransactionResult:
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
