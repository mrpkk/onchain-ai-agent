"""OpenAI-совместимый провайдер: DeepSeek, Qwen, РФ-агрегаторы, Ollama."""

from __future__ import annotations

import time

import httpx

from .base import LLMProvider, LLMResult, ProviderError


class OpenAICompatibleProvider(LLMProvider):
    """Любой endpoint с POST {base_url}/chat/completions."""

    def __init__(self, name: str, base_url: str, api_key: str = "",
                 model: str = "gpt-4o-mini"):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete(self, system: str, user: str, *, temperature: float = 0.3,
                       json_mode: bool = True, timeout: float = 30.0) -> LLMResult:
        payload: dict = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 2048,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers,
                )
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name}: network error: {e}", retryable=True) from e

        if response.status_code >= 400:
            retryable = response.status_code in (408, 409, 425, 429) or response.status_code >= 500
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}: {response.text[:200]}",
                retryable=retryable, status=response.status_code,
            )

        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError(f"{self.name}: unexpected response: {e}", retryable=False) from e

        usage = data.get("usage") or {}
        return LLMResult(
            text=text or "",
            provider=self.name,
            model=data.get("model", self.model),
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_prompt=usage.get("prompt_tokens"),
            tokens_completion=usage.get("completion_tokens"),
        )
