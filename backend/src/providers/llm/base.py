"""Базовые типы LLM-провайдеров (SPEC S2-05)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResult:
    """Результат LLM-вызова с метаданными для трейсинга (S2-06)."""

    text: str
    provider: str
    model: str = ""
    latency_ms: int = 0
    tokens_prompt: Optional[int] = None
    tokens_completion: Optional[int] = None
    attempts: int = 1


class ProviderError(Exception):
    """Ошибка провайдера; retryable управляет повтором в роутере."""

    def __init__(self, message: str, *, retryable: bool = True,
                 status: Optional[int] = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LLMProvider(ABC):
    """Единый контракт LLM-провайдера (OpenAI-совместимые + GigaChat)."""

    name: str = "provider"
    model: str = ""

    @abstractmethod
    async def complete(self, system: str, user: str, *, temperature: float = 0.3,
                       json_mode: bool = True, timeout: float = 30.0) -> LLMResult:
        """Один вызов чата. Raises ProviderError."""

    async def health(self) -> bool:
        try:
            await self.complete("ping", "ping", json_mode=False, timeout=5.0)
            return True
        except Exception:
            return False
