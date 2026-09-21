"""NL → Dharma-правило (SPEC S4-10, фича «Intent→Guarantee»).

Пользователь формулирует правило словами («не трать больше 0.05 ETH в день»),
LLM превращает это в структурированный патч политики; патч валидируется
компилятором Dharma и возвращается как YAML-превью. Применение — только
через явное подтверждение (PUT /policy → новая версия).
"""

from __future__ import annotations

from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from ..providers.llm import LLMResult, build_default_router
from ..security.dharma import PolicyError, compile_policy, compile_yaml

POLICY_INTENT_PROMPT_VERSION = "policy-intent-1.0"


class PolicyIntentSchema(BaseModel):
    rule_type: Literal["limits", "deny_addresses", "allow_addresses",
                       "approvals", "undo", "noop"]
    params: dict = Field(default_factory=dict)
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_clarification: bool = False
    questions: list[str] = Field(default_factory=list)


POLICY_INTENT_SYSTEM_PROMPT = """Ты — парсер правил безопасности для ончейн-агента KARTA.
Преобразуй правило пользователя в JSON-патч Dharma-политики. Ничего не выдумывай:
если правило непонятно — rule_type="noop", needs_clarification=true и questions[].

Схема:
{
  "rule_type": "limits|deny_addresses|allow_addresses|approvals|undo|noop",
  "params": {
    // limits: {per_tx_eth?: float, daily_eth?: float, gas_gwei_cap?: int, slippage_bps_max?: int}
    // deny_addresses: {addresses: ["0x..."]}
    // allow_addresses: {addresses: ["0x..."]}
    // approvals: {amount_eth_gte?: float, risk_score_gte?: float}
    // undo: {window_seconds?: int, threshold_eth?: float}
  },
  "summary": "человеческое резюме правила",
  "confidence": 0.0-1.0,
  "needs_clarification": false,
  "questions": []
}
Отвечай ТОЛЬКО JSON."""

POLICY_INTENT_USER_TEMPLATE = """Правило пользователя:
\"\"\"{text}\"\"\"

Верни JSON по схеме."""


async def parse_policy_rule(text: str, router=None) -> tuple[PolicyIntentSchema, LLMResult]:
    router = router or build_default_router()
    return await router.complete_json(
        POLICY_INTENT_SYSTEM_PROMPT,
        POLICY_INTENT_USER_TEMPLATE.format(text=text),
        PolicyIntentSchema,
        temperature=0.2,
        prompt_version=POLICY_INTENT_PROMPT_VERSION,
    )


def _patch_from_rule(rule: PolicyIntentSchema) -> dict:
    params = rule.params or {}
    if rule.rule_type == "limits":
        limits = {}
        for key in ("per_tx_eth", "daily_eth", "gas_gwei_cap", "slippage_bps_max"):
            if key in params and params[key] is not None:
                limits[key] = params[key]
        return {"limits": limits} if limits else {}
    if rule.rule_type == "deny_addresses":
        addrs = [str(a).lower() for a in params.get("addresses", []) if a]
        return {"deny": {"addresses": addrs}}
    if rule.rule_type == "allow_addresses":
        addrs = [str(a).lower() for a in params.get("addresses", []) if a]
        return {"allow": {"addresses": addrs}}
    if rule.rule_type == "approvals":
        required_if = {}
        if params.get("amount_eth_gte") is not None:
            required_if["amount_eth_gte"] = params["amount_eth_gte"]
        if params.get("risk_score_gte") is not None:
            required_if["risk_score_gte"] = params["risk_score_gte"]
        return {"approvals": {"required_if": required_if}} if required_if else {}
    if rule.rule_type == "undo":
        undo = {}
        if params.get("window_seconds") is not None:
            undo["window_seconds"] = int(params["window_seconds"])
        if params.get("threshold_eth") is not None:
            undo["threshold_eth"] = params["threshold_eth"]
        return {"undo": undo} if undo else {}
    return {}


def _deep_merge(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_policy_yaml(base_yaml: Optional[str],
                      rule: PolicyIntentSchema) -> tuple[str, dict]:
    """Мержит патч правила с текущей политикой и валидирует результат.

    Returns: (yaml_str, patch). Raises PolicyError при невалидном результате.
    """
    if base_yaml:
        base_model = compile_yaml(base_yaml).model.model_dump(mode="json")
    else:
        base_model = compile_policy({}).model.model_dump(mode="json")

    patch = _patch_from_rule(rule)
    if not patch:
        raise PolicyError("Правило не содержит изменений политики")

    merged = _deep_merge(base_model, patch)
    compile_policy(merged)  # валидация fail-closed
    yaml_str = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)
    return yaml_str, patch
