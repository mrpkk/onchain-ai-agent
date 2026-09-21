"""NL → структурированный intent (SPEC S4-03: chat-first).

Парсер превращает человеческий запрос («Переведи 50 USDC на 0x…, когда газ < 20»)
в структуру. LLM предлагает — Dharma и симуляция решают при исполнении.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..providers.llm import LLMResult, build_default_router

INTENT_PROMPT_VERSION = "intent-1.0"


class IntentSchema(BaseModel):
    """Структурированное намерение пользователя."""

    action: Literal["transfer", "swap", "approve", "contract_call",
                    "monitor", "hold", "unknown"]
    params: dict = Field(default_factory=dict)
    summary: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    questions: list[str] = Field(default_factory=list)


INTENT_SYSTEM_PROMPT = """Ты — парсер намерений для ончейн-агента KARTA.
Преобразуй запрос пользователя в JSON. Никаких выдуманных адресов/сумм:
если данных не хватает — needs_clarification=true и questions[].

Схема:
{
  "action": "transfer|swap|approve|contract_call|monitor|hold|unknown",
  "params": {...},            // transfer: {to, amount, token, condition?}; monitor: {target, condition?}; и т.п.
  "summary": "человеческое резюме намерения",
  "confidence": 0.0-1.0,
  "assumptions": ["что предположено"],
  "needs_clarification": false,
  "questions": ["чего не хватает"]
}
Отвечай ТОЛЬКО JSON."""

INTENT_USER_TEMPLATE = """Запрос пользователя:
\"\"\"{text}\"\"\"

Верни JSON по схеме."""


async def parse_intent(text: str, router=None) -> tuple[IntentSchema, LLMResult]:
    """Парсит NL-запрос в IntentSchema. Raises AllProvidersFailed."""
    router = router or build_default_router()
    return await router.complete_json(
        INTENT_SYSTEM_PROMPT,
        INTENT_USER_TEMPLATE.format(text=text),
        IntentSchema,
        temperature=0.2,
        prompt_version=INTENT_PROMPT_VERSION,
    )
