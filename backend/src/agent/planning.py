"""
Planning Layer — decomposes high-level goals into executable on-chain operations.

Takes a user goal (e.g., "maximize yield") and produces a step-by-step plan
of blockchain transactions.
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("agent.planning")


class PlanStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class StepType(Enum):
    READ_STATE = "read_state"
    TRANSFER = "transfer"
    CONTRACT_CALL = "contract_call"
    APPROVE = "approve"
    SWAP = "swap"
    BRIDGE = "bridge"
    DEPLOY = "deploy"
    WAIT = "wait"
    CONDITIONAL = "conditional"


@dataclass
class PlanStep:
    id: str
    step_type: StepType
    description: str
    chain: str
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    gas_estimate: int = 0
    requires_approval: bool = False


@dataclass
class Plan:
    id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    current_step: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.status == PlanStatus.COMPLETED)
        return completed / len(self.steps)

    @property
    def is_done(self) -> bool:
        return all(s.status in (PlanStatus.COMPLETED, PlanStatus.CANCELLED) for s in self.steps)

    @property
    def has_failures(self) -> bool:
        return any(s.status == PlanStatus.FAILED for s in self.steps)

    def get_next_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status == PlanStatus.PENDING:
                deps_met = all(
                    self._get_step(dep).status == PlanStatus.COMPLETED
                    for dep in step.depends_on
                    if self._get_step(dep)
                )
                if deps_met:
                    return step
        return None

    def _get_step(self, step_id: str) -> Optional[PlanStep]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


class AgentPlanner:
    """Creates plans from high-level goals."""

    PREDEFINED_STRATEGIES = {
        "yield_optimization": {
            "description": "Find and deploy to highest yield DeFi protocol",
            "steps": [
                {"type": "read_state", "desc": "Check wallet balances across chains", "chain": "ethereum"},
                {"type": "read_state", "desc": "Query DeFi yields (Aave, Compound, Yearn)", "chain": "ethereum"},
                {"type": "contract_call", "desc": "Compare yields and select best protocol", "chain": "ethereum"},
                {"type": "approve", "desc": "Approve token spending for target protocol", "chain": "ethereum"},
                {"type": "contract_call", "desc": "Deposit funds into yield protocol", "chain": "ethereum"},
                {"type": "wait", "desc": "Monitor position and rebalance if needed", "chain": "ethereum"},
            ],
        },
        "cross_chain_arbitrage": {
            "description": "Find and execute arbitrage between chains",
            "steps": [
                {"type": "read_state", "desc": "Check prices on Chain A and Chain B", "chain": "ethereum"},
                {"type": "read_state", "desc": "Calculate spread and gas costs", "chain": "ethereum"},
                {"type": "conditional", "desc": "Is spread > gas + profit margin?", "chain": "ethereum"},
                {"type": "swap", "desc": "Buy on cheaper chain", "chain": "bsc"},
                {"type": "bridge", "desc": "Bridge tokens to target chain", "chain": "bsc"},
                {"type": "swap", "desc": "Sell on expensive chain", "chain": "ethereum"},
            ],
        },
        "ricardian_contract": {
            "description": "Create and execute a Ricardian agreement",
            "steps": [
                {"type": "deploy", "desc": "Deploy RicardianAgreement contract", "chain": "ethereum"},
                {"type": "contract_call", "desc": "Register agreement with terms", "chain": "ethereum"},
                {"type": "contract_call", "desc": "Wait for counterparty signature", "chain": "ethereum"},
                {"type": "contract_call", "desc": "Execute milestones as they complete", "chain": "ethereum"},
            ],
        },
    }

    def create_plan(self, goal: str, context: dict = None) -> Plan:
        plan_id = f"plan_{hash(goal) % 100000:05d}"
        context = context or {}

        for strategy_key, strategy in self.PREDEFINED_STRATEGIES.items():
            if strategy_key in goal.lower() or any(kw in goal.lower() for kw in strategy_key.split("_")):
                return self._build_plan_from_strategy(plan_id, goal, strategy, context)

        return self._build_generic_plan(plan_id, goal, context)

    def _build_plan_from_strategy(self, plan_id: str, goal: str,
                                   strategy: dict, context: dict) -> Plan:
        steps = []
        for i, step_def in enumerate(strategy["steps"]):
            steps.append(PlanStep(
                id=f"{plan_id}_step_{i}",
                step_type=StepType(step_def["type"]),
                description=step_def["desc"],
                chain=step_def.get("chain", "ethereum"),
                depends_on=[f"{plan_id}_step_{i-1}"] if i > 0 else [],
            ))

        plan = Plan(
            id=plan_id,
            goal=goal,
            steps=steps,
            metadata={"strategy": strategy["description"]},
        )
        logger.info(f"Created plan {plan_id} with {len(steps)} steps from strategy")
        return plan

    def _build_generic_plan(self, plan_id: str, goal: str, context: dict) -> Plan:
        steps = [
            PlanStep(
                id=f"{plan_id}_step_0",
                step_type=StepType.READ_STATE,
                description="Gather current blockchain state and wallet balances",
                chain=context.get("chain", "ethereum"),
            ),
            PlanStep(
                id=f"{plan_id}_step_1",
                step_type=StepType.READ_STATE,
                description=f"Analyze data to determine best action for: {goal}",
                chain=context.get("chain", "ethereum"),
                depends_on=[f"{plan_id}_step_0"],
            ),
            PlanStep(
                id=f"{plan_id}_step_2",
                step_type=StepType.CONTRACT_CALL,
                description="Execute the determined action",
                chain=context.get("chain", "ethereum"),
                depends_on=[f"{plan_id}_step_1"],
                requires_approval=True,
            ),
        ]

        plan = Plan(
            id=plan_id,
            goal=goal,
            steps=steps,
            metadata={"strategy": "generic"},
        )
        logger.info(f"Created generic plan {plan_id} with {len(steps)} steps")
        return plan

    def estimate_total_gas(self, plan: Plan) -> int:
        return sum(s.gas_estimate for s in plan.steps)

    def summarize(self, plan: Plan) -> str:
        lines = [f"Plan: {plan.goal}", f"Status: {plan.status.value}",
                 f"Progress: {plan.progress:.0%}", ""]
        for step in plan.steps:
            status_icon = {
                PlanStatus.PENDING: "[ ]",
                PlanStatus.IN_PROGRESS: "[>]",
                PlanStatus.COMPLETED: "[x]",
                PlanStatus.FAILED: "[!]",
                PlanStatus.BLOCKED: "[-]",
            }.get(step.status, "[?]")
            lines.append(f"  {status_icon} {step.description} ({step.chain})")
        return "\n".join(lines)
