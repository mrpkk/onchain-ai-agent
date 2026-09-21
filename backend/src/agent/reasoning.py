"""
Reasoning Layer — LLM-powered decision making for on-chain agents.

Uses Chain-of-Thought prompting for reliable reasoning about blockchain operations.

Приоритет провайдеров (SPEC S2-05):
    1. GigaChat (Сбер) — первичный, работает из РФ
    2. DeepSeek → 3. Qwen → 4. РФ-агрегатор → 5. Ollama (локальная)
Ключи читаются из ~/.env. Структурированный вывод валидируется pydantic-схемой;
invalid → repair → следующий провайдер → fail-safe ask_human.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from ..providers.llm import AllProvidersFailed, build_default_router

# ── Загрузка ключей из ~/.env ─────────────────────────────────────────
load_dotenv(os.path.expanduser("~/.env"), override=True)

# ── GigaChat (Сбер) — первичный (детали: providers/llm/gigachat.py) ────
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY", "")

logger = logging.getLogger("agent.reasoning")


@dataclass
class AgentDecision:
    action: str
    params: dict
    reasoning: str
    confidence: float
    risk_level: str  # low, medium, high, critical
    estimated_gas: int = 0
    requires_approval: bool = False


class AgentDecisionSchema(BaseModel):
    """Схема структурированного решения — валидация вывода LLM (S2-05)."""

    action: Literal["transfer", "contract_call", "deploy", "approve", "swap",
                    "bridge", "hold", "ask_human"]
    params: dict = Field(default_factory=dict)
    reasoning: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    estimated_gas: int = 0
    requires_approval: bool = False


SYSTEM_PROMPT = """You are an autonomous on-chain AI agent. You analyze blockchain data and make decisions about executing smart contract operations.

## Your Capabilities:
- Read blockchain state (balances, contract states, events)
- Execute transactions (transfers, contract calls, deployments)
- Manage wallets with spending limits
- Interact with DeFi protocols (Uniswap, Aave, Compound)
- Deploy and interact with Ricardian contracts

## Safety Rules:
1. NEVER exceed spending limits
2. ALWAYS verify contract addresses before interaction
3. ALWAYS estimate gas before execution
4. Log every decision with reasoning
5. If unsure, ask for human approval (risk_level: critical)
6. NEVER expose private keys in responses

## Response Format:
You MUST respond with valid JSON matching this schema:
{
    "action": "transfer|contract_call|deploy|approve|swap|bridge|hold|ask_human",
    "params": { ... },
    "reasoning": "Chain-of-thought explanation",
    "confidence": 0.0-1.0,
    "risk_level": "low|medium|high|critical",
    "estimated_gas": 0,
    "requires_approval": false
}

## Common Actions:
- transfer: {"to": "0x...", "amount": 0.1, "token": "ETH", "chain": "ethereum"}
- contract_call: {"address": "0x...", "abi": [...], "function": "deposit", "args": [...], "value": 0}
- deploy: {"contract": "RicardianAgreement", "constructor_args": [...]}
- approve: {"token": "0x...", "spender": "0x...", "amount": 100.0}  # exact amount ONLY; infinite/max approval is blocked by security policy
- swap: {"token_in": "0x...", "token_out": "0x...", "amount": 0.1, "dex": "uniswap"}
- hold: {"reason": "Waiting for better conditions"}
- ask_human: {"question": "What should I do?", "options": ["A", "B"]}
"""

USER_PROMPT_TEMPLATE = """## Current State
{state}

## Goal
{goal}

## Recent Actions
{history}

## Task
Analyze the current state and decide the best action to achieve the goal. Consider gas costs, risks, and optimal timing.

Respond with JSON only. No markdown."""


class LLMReasoner:
    """Принимает решения через LLM-роутер (SPEC S2-05).

    Цепочка: GigaChat → DeepSeek → Qwen → агрегатор → Ollama (по env-ключам).
    Структурированный вывод (pydantic) + repair; полный отказ → ask_human (critical).
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "mistral-small-latest",
                 base_url: str = "https://api.mistral.ai/v1", router=None):
        # api_key/model/base_url сохранены для совместимости конструктора;
        # фактическая цепочка — LLMRouter (build_default_router из окружения).
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self._router = router
        self._decision_history: list[AgentDecision] = []

    def _get_router(self):
        if self._router is None:
            self._router = build_default_router()
        return self._router

    async def decide(self, state: dict, goal: str, history: list[dict] = None,
                     temperature: float = 0.3) -> AgentDecision:
        state_str = json.dumps(state, indent=2, default=str)
        history_str = json.dumps(history or self._format_history(), indent=2, default=str)
        user_msg = USER_PROMPT_TEMPLATE.format(state=state_str, goal=goal, history=history_str)

        try:
            router = self._get_router()
            parsed, result = await router.complete_json(
                SYSTEM_PROMPT, user_msg, AgentDecisionSchema, temperature=temperature,
            )
            decision = AgentDecision(
                action=parsed.action,
                params=parsed.params,
                reasoning=parsed.reasoning,
                confidence=parsed.confidence,
                risk_level=parsed.risk_level,
                estimated_gas=parsed.estimated_gas,
                requires_approval=parsed.requires_approval,
            )
            logger.info(
                "Decision via %s/%s (%d ms, tokens=%s+%s): %s (confidence=%.2f, risk=%s)",
                result.provider, result.model, result.latency_ms,
                result.tokens_prompt, result.tokens_completion,
                decision.action, decision.confidence, decision.risk_level,
            )
            self._decision_history.append(decision)
            return decision
        except AllProvidersFailed as e:
            logger.error("Все LLM-провайдеры недоступны: %s", e)
            return AgentDecision(
                action="ask_human",
                params={"question": f"LLM unavailable: {e}"},
                reasoning=f"All providers failed: {e}"[:500],
                confidence=0.0,
                risk_level="critical",
                requires_approval=True,
            )
        except Exception as e:  # noqa: BLE001 — fail-safe (SPEC: ошибка → ask_human)
            logger.error("Reasoning error: %s", e)
            return AgentDecision(
                action="ask_human",
                params={"question": f"LLM reasoning failed: {e}. What should I do?"},
                reasoning=f"Error in LLM call: {e}",
                confidence=0.0,
                risk_level="critical",
                requires_approval=True,
            )

    def _format_history(self) -> list[dict]:
        return [
            {
                "action": d.action,
                "params": d.params,
                "reasoning": d.reasoning[:200],
                "risk_level": d.risk_level,
            }
            for d in self._decision_history[-10:]
        ]


class RiskAssessor:
    """Evaluates risk of proposed actions before execution."""

    HIGH_RISK_THRESHOLD_GAS = 500_000
    CRITICAL_RISK_THRESHOLD_VALUE = 1.0  # ETH
    DAILY_SPEND_LIMIT = 5.0  # ETH

    def __init__(self):
        self._daily_spend: float = 0.0
        self._blocked_addresses: set[str] = set()
        self._allowed_contracts: set[str] = set()

    def assess(self, decision: AgentDecision, current_balance: float,
               daily_spent: float = 0.0) -> AgentDecision:
        risk_score = 0.0

        if decision.action in ("transfer", "contract_call", "swap", "bridge"):
            value = decision.params.get("amount", 0)
            if isinstance(value, (int, float)):
                if value > self.CRITICAL_RISK_THRESHOLD_VALUE:
                    risk_score += 0.4
                if value > current_balance * 0.5:
                    risk_score += 0.3

        if decision.estimated_gas > self.HIGH_RISK_THRESHOLD_GAS:
            risk_score += 0.2

        if daily_spent + decision.params.get("amount", 0) > self.DAILY_SPEND_LIMIT:
            risk_score += 0.5
            decision.requires_approval = True

        to_address = decision.params.get("to", decision.params.get("address", ""))
        if to_address.lower() in self._blocked_addresses:
            risk_score = 1.0
            decision.requires_approval = True

        if risk_score > 0.7:
            decision.risk_level = "critical"
            decision.requires_approval = True
        elif risk_score > 0.4:
            decision.risk_level = "high"
        elif risk_score > 0.2:
            decision.risk_level = "medium"

        return decision

    def block_address(self, address: str):
        self._blocked_addresses.add(address.lower())

    def allow_contract(self, address: str):
        self._allowed_contracts.add(address.lower())
