"""LLMRouter — цепочка провайдеров, circuit breaker, structured output (SPEC S2-05).

Порядок: GigaChat → DeepSeek → Qwen → РФ-агрегатор → Ollama.
Invalid JSON → repair-попытка → следующий провайдер → AllProvidersFailed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from pydantic import BaseModel, ValidationError

from .base import LLMProvider, LLMResult, ProviderError
from .gigachat import GigaChatProvider
from .openai_compat import OpenAICompatibleProvider

logger = logging.getLogger("providers.router")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class AllProvidersFailed(Exception):
    """Ни один провайдер не дал валидный ответ."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        summary = "; ".join(f"{name}: {err}" for name, err in errors.items()) or "no providers"
        super().__init__(summary)


@dataclass
class CircuitBreaker:
    """Размыкает провайдера после N ошибок на cooldown секунд."""

    threshold: int = 3
    cooldown_s: float = 60.0
    failures: int = 0
    open_until: float = 0.0

    def allow(self) -> bool:
        return time.monotonic() >= self.open_until

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.cooldown_s
            self.failures = 0
            logger.warning("Circuit breaker open for %.0fs", self.cooldown_s)

    def on_success(self) -> None:
        self.failures = 0


def extract_json(text: str) -> str:
    """Достаёт JSON из ответа LLM (в т.ч. из ```json ...```)."""
    text = (text or "").strip()
    match = _JSON_FENCE.search(text)
    if match:
        return match.group(1).strip()
    if text.startswith("{"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return text


class LLMRouter:
    def __init__(self, providers: Sequence[LLMProvider], *,
                 max_attempts_per_provider: int = 2,
                 repair_attempts: int = 1,
                 breaker_threshold: int = 3,
                 breaker_cooldown_s: float = 60.0):
        self.providers = list(providers)
        self.max_attempts_per_provider = max_attempts_per_provider
        self.repair_attempts = repair_attempts
        self._breakers = {
            provider.name: CircuitBreaker(threshold=breaker_threshold,
                                          cooldown_s=breaker_cooldown_s)
            for provider in self.providers
        }

    async def complete_json(self, system: str, user: str,
                            schema: type[BaseModel], *,
                            temperature: float = 0.3) -> tuple[BaseModel, LLMResult]:
        """Возвращает (валидированная модель, результат вызова)."""
        errors: dict[str, str] = {}
        for provider in self.providers:
            breaker = self._breakers[provider.name]
            if not breaker.allow():
                errors[provider.name] = "circuit breaker open"
                continue

            prompt = user
            for attempt in range(self.max_attempts_per_provider):
                try:
                    result = await provider.complete(system, prompt,
                                                     temperature=temperature)
                except ProviderError as e:
                    errors[provider.name] = str(e)
                    breaker.on_failure()
                    if not e.retryable:
                        break
                    continue
                except Exception as e:  # noqa: BLE001 — изоляция провайдера
                    errors[provider.name] = f"unexpected: {e}"
                    breaker.on_failure()
                    break

                try:
                    parsed = schema.model_validate_json(extract_json(result.text))
                except ValidationError as e:
                    errors[provider.name] = f"invalid json: {str(e)[:200]}"
                    if attempt < self.repair_attempts:
                        prompt = (
                            f"{user}\n\nВАЖНО: верни ТОЛЬКО валидный JSON по схеме. "
                            f"Прошлый ответ не прошёл валидацию: {str(e)[:300]}"
                        )
                        continue
                    break

                breaker.on_success()
                return parsed, result

        raise AllProvidersFailed(errors)


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def build_default_router() -> LLMRouter:
    """Собирает цепочку по доступным ключам окружения (~/.env)."""
    providers: list[LLMProvider] = []

    if os.getenv("GIGACHAT_AUTH_KEY"):
        providers.append(GigaChatProvider(
            os.getenv("GIGACHAT_AUTH_KEY", ""),
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            model=os.getenv("GIGACHAT_MODEL", "GigaChat-Max"),
            rquid=os.getenv("GIGACHAT_RQUID", ""),
        ))

    deepseek_key = _first_env(*[f"DEEPSEEK_API_KEY_{i}" for i in range(6)],
                              "DEEPSEEK_API_KEY")
    if deepseek_key:
        providers.append(OpenAICompatibleProvider(
            "deepseek", "https://api.deepseek.com/v1", deepseek_key,
            os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        ))

    qwen_key = _first_env("QWEN_API_KEY", "DASHSCOPE_API_KEY")
    if qwen_key:
        providers.append(OpenAICompatibleProvider(
            "qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", qwen_key,
            os.getenv("QWEN_MODEL", "qwen-plus"),
        ))

    aggregator_url = _first_env("KARTA_AGGREGATOR_BASE_URL", "AGGREGATOR_BASE_URL")
    if aggregator_url:
        providers.append(OpenAICompatibleProvider(
            "aggregator", aggregator_url,
            _first_env("KARTA_AGGREGATOR_API_KEY", "AGGREGATOR_API_KEY") or "",
            os.getenv("AGGREGATOR_MODEL", "gpt-4o-mini"),
        ))

    if os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_ENABLE", "").lower() in (
            "1", "true", "on"):
        providers.append(OpenAICompatibleProvider(
            "ollama", os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"), "",
            os.getenv("OLLAMA_MODEL", "llama3.1"),
        ))

    if not providers:
        raise AllProvidersFailed({
            "*": "нет ни одного провайдера: задайте GIGACHAT_AUTH_KEY, "
                 "DEEPSEEK_API_KEY_*, QWEN_API_KEY, AGGREGATOR_BASE_URL или OLLAMA_BASE_URL",
        })
    return LLMRouter(providers)
