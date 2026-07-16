"""
Reasoning Layer — LLM-powered decision making for on-chain agents.

Uses Chain-of-Thought prompting for reliable reasoning about blockchain operations.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

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
- approve: {"token": "0x...", "spender": "0x...", "amount": "max"}
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
    """Makes decisions using an LLM (Mistral AI or compatible API)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "mistral-small-latest",
                 base_url: str = "https://api.mistral.ai/v1"):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self._decision_history: list[AgentDecision] = []

    async def decide(self, state: dict, goal: str, history: list[dict] = None,
                     temperature: float = 0.3) -> AgentDecision:
        state_str = json.dumps(state, indent=2, default=str)
        history_str = json.dumps(history or self._format_history(), indent=2, default=str)

        user_msg = USER_PROMPT_TEMPLATE.format(
            state=state_str,
            goal=goal,
            history=history_str,
        )

        try:
            response_text = await self._call_llm(SYSTEM_PROMPT, user_msg, temperature)
            decision = self._parse_decision(response_text)
            self._decision_history.append(decision)
            logger.info(f"Decision: {decision.action} (confidence={decision.confidence}, risk={decision.risk_level})")
            return decision
        except Exception as e:
            logger.error(f"Reasoning error: {e}")
            return AgentDecision(
                action="ask_human",
                params={"question": f"LLM reasoning failed: {e}. What should I do?"},
                reasoning=f"Error in LLM call: {e}",
                confidence=0.0,
                risk_level="critical",
                requires_approval=True,
            )

    async def _call_llm(self, system: str, user: str, temperature: float = 0.3) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "max_tokens": 2048,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    def _parse_decision(self, text: str) -> AgentDecision:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                return AgentDecision(
                    action="ask_human",
                    params={"question": "Could not parse LLM response"},
                    reasoning=text[:500],
                    confidence=0.0,
                    risk_level="critical",
                    requires_approval=True,
                )

        return AgentDecision(
            action=data.get("action", "hold"),
            params=data.get("params", {}),
            reasoning=data.get("reasoning", ""),
            confidence=float(data.get("confidence", 0.5)),
            risk_level=data.get("risk_level", "medium"),
            estimated_gas=int(data.get("estimated_gas", 0)),
            requires_approval=bool(data.get("requires_approval", False)),
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
