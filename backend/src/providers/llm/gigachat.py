"""GigaChat (Сбер) — первичный провайдер для РФ (OAuth + chat completions)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

import httpx

from .base import LLMProvider, LLMResult, ProviderError

logger = logging.getLogger("providers.gigachat")

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatProvider(LLMProvider):
    name = "gigachat"

    def __init__(self, auth_key: str, scope: str = "GIGACHAT_API_PERS",
                 model: str = "GigaChat-Max", rquid: str = ""):
        if not auth_key:
            raise ProviderError("gigachat: auth key is empty", retryable=False)
        self.auth_key = auth_key
        self.scope = scope
        self.model = model
        self.rquid = rquid
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    async def _access_token(self, timeout: float) -> str:
        now = time.time()
        if self._token and self._expires_at > now + 60:
            return self._token
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:  # noqa: S501 — НУЦ Минцифры
                response = await client.post(
                    OAUTH_URL,
                    data={"scope": self.scope},
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                        "RqUID": self.rquid or str(uuid.uuid4()),
                        "Authorization": f"Basic {self.auth_key}",
                    },
                )
        except httpx.HTTPError as e:
            raise ProviderError(f"gigachat: auth network error: {e}", retryable=True) from e

        if response.status_code >= 400:
            raise ProviderError(
                f"gigachat: auth HTTP {response.status_code}: {response.text[:200]}",
                retryable=response.status_code >= 500 or response.status_code == 429,
                status=response.status_code,
            )
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise ProviderError("gigachat: no access_token in OAuth response", retryable=False)
        self._token = token
        self._expires_at = now + float(data.get("expires_in", 1800)) - 60
        return token

    async def complete(self, system: str, user: str, *, temperature: float = 0.3,
                       json_mode: bool = True, timeout: float = 30.0) -> LLMResult:
        token = await self._access_token(min(timeout, 15.0))
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:  # noqa: S501
                response = await client.post(
                    BASE_URL, json=payload,
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                )
        except httpx.HTTPError as e:
            raise ProviderError(f"gigachat: network error: {e}", retryable=True) from e

        if response.status_code == 401:
            self._token = None  # токен протух — следующий вызов переполучит
            raise ProviderError("gigachat: unauthorized (token expired)", retryable=True,
                                status=401)
        if response.status_code >= 400:
            raise ProviderError(
                f"gigachat: HTTP {response.status_code}: {response.text[:200]}",
                retryable=response.status_code >= 500 or response.status_code == 429,
                status=response.status_code,
            )
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError(f"gigachat: unexpected response: {e}", retryable=False) from e

        usage = data.get("usage") or {}
        return LLMResult(
            text=text or "",
            provider=self.name,
            model=data.get("model", self.model),
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_prompt=usage.get("prompt_tokens"),
            tokens_completion=usage.get("completion_tokens"),
        )
