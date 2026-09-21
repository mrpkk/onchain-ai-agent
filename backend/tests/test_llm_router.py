"""Тесты S2-05: LLMRouter (fallback/repair/breaker), провайдеры, fail-safe reasoner."""
import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.reasoning import AgentDecision, LLMReasoner  # noqa: E402
from src.providers.llm import (  # noqa: E402
    AllProvidersFailed,
    LLMProvider,
    LLMResult,
    LLMRouter,
    ProviderError,
    extract_json,
)


class EchoSchema(BaseModel):
    value: int


class ScriptedProvider(LLMProvider):
    """Провайдер с запрограммированным сценарием ответов."""

    def __init__(self, name: str, script: list):
        self.name = name
        self.model = "scripted"
        self.script = list(script)
        self.calls: list[str] = []

    async def complete(self, system: str, user: str, *, temperature: float = 0.3,
                       json_mode: bool = True, timeout: float = 30.0) -> LLMResult:
        self.calls.append(user)
        item = self.script.pop(0) if self.script else self.script[-1]
        if isinstance(item, Exception):
            raise item
        return LLMResult(text=item, provider=self.name, model=self.model, latency_ms=1)


def _run(coro):
    return asyncio.run(coro)


def test_router_first_provider_wins():
    first = ScriptedProvider("first", ['{"value": 1}'])
    second = ScriptedProvider("second", ['{"value": 2}'])
    router = LLMRouter([first, second])
    parsed, result = _run(router.complete_json("s", "u", EchoSchema))
    assert parsed.value == 1
    assert result.provider == "first"
    assert second.calls == []


def test_router_falls_back_to_second_provider():
    first = ScriptedProvider("first", [ProviderError("boom", retryable=True),
                                       ProviderError("boom2", retryable=True)])
    second = ScriptedProvider("second", ['{"value": 7}'])
    router = LLMRouter([first, second])
    parsed, result = _run(router.complete_json("s", "u", EchoSchema))
    assert parsed.value == 7
    assert result.provider == "second"
    assert len(first.calls) == 2  # две попытки на первом


def test_router_repairs_invalid_json_same_provider():
    provider = ScriptedProvider("p", ["not json at all", '{"value": 5}'])
    router = LLMRouter([provider], max_attempts_per_provider=2, repair_attempts=1)
    parsed, _ = _run(router.complete_json("s", "u", EchoSchema))
    assert parsed.value == 5
    assert "валидный JSON" in provider.calls[1]


def test_router_all_providers_failed():
    first = ScriptedProvider("first", [ProviderError("down", retryable=False)])
    second = ScriptedProvider("second", [ProviderError("down2", retryable=False)])
    router = LLMRouter([first, second])
    with pytest.raises(AllProvidersFailed) as exc:
        _run(router.complete_json("s", "u", EchoSchema))
    assert set(exc.value.errors) == {"first", "second"}


def test_circuit_breaker_opens_and_skips():
    provider = ScriptedProvider("flaky", [ProviderError("x", retryable=True)] * 10)
    router = LLMRouter([provider], max_attempts_per_provider=2, breaker_threshold=2,
                       breaker_cooldown_s=60.0)
    with pytest.raises(AllProvidersFailed):
        _run(router.complete_json("s", "u", EchoSchema))
    assert len(provider.calls) == 2  # исчерпал попытки и открыл breaker
    with pytest.raises(AllProvidersFailed):
        _run(router.complete_json("s", "u", EchoSchema))
    assert len(provider.calls) == 2  # breaker открыт — провайдер не вызывался


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == '{"a": 1}'
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Вот результат: {"a": 1} — готово') == '{"a": 1}'


def test_reasoner_fail_safe_on_all_providers_failed():
    failing = ScriptedProvider("dead", [ProviderError("net", retryable=False)])
    reasoner = LLMReasoner(router=LLMRouter([failing]))
    decision = _run(reasoner.decide(state={}, goal="test"))
    assert decision.action == "ask_human"
    assert decision.risk_level == "critical"
    assert decision.requires_approval is True


def test_reasoner_maps_valid_schema():
    payload = ('{"action": "transfer", "params": {"to": "0xabc", "amount": 0.1}, '
               '"reasoning": "test", "confidence": 0.9, "risk_level": "low", '
               '"estimated_gas": 21000, "requires_approval": false}')
    provider = ScriptedProvider("good", [payload])
    reasoner = LLMReasoner(router=LLMRouter([provider]))
    decision = _run(reasoner.decide(state={}, goal="test"))
    assert isinstance(decision, AgentDecision)
    assert decision.action == "transfer"
    assert decision.confidence == pytest.approx(0.9)
    assert decision.requires_approval is False


# ── HTTP-слой OpenAI-совместимого провайдера ──────────────────────────

class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _CannedHTTP:
    """Замена httpx.AsyncClient: отдаёт заранее заготовленные ответы по URL."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        return _Client(self)


class _Client:
    def __init__(self, canned: _CannedHTTP):
        self.canned = canned

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None, data=None):
        self.canned.calls.append({"url": url, "json": json, "headers": headers})
        for index, (substring, status, payload) in enumerate(self.canned.responses):
            if substring in url:
                self.canned.responses.pop(index)
                return _Response(status, payload)
        return _Response(500, {"error": "no canned response"})


def test_openai_compatible_success(monkeypatch):
    from src.providers.llm import openai_compat as module

    canned = _CannedHTTP([
        ("chat/completions", 200, {
            "model": "deepseek-chat",
            "choices": [{"message": {"content": '{"value": 3}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
        }),
    ])
    monkeypatch.setattr(module.httpx, "AsyncClient", canned)
    provider = module.OpenAICompatibleProvider("deepseek", "https://api.deepseek.com/v1",
                                               "key", "deepseek-chat")
    result = _run(provider.complete("s", "u"))
    assert result.text == '{"value": 3}'
    assert result.tokens_prompt == 10
    assert result.tokens_completion == 4
    assert canned.calls[0]["headers"]["Authorization"] == "Bearer key"


def test_openai_compatible_error_mapping(monkeypatch):
    from src.providers.llm import openai_compat as module

    canned = _CannedHTTP([("chat/completions", 429, {"error": "rate limit"})])
    monkeypatch.setattr(module.httpx, "AsyncClient", canned)
    provider = module.OpenAICompatibleProvider("deepseek", "https://x/v1", "key", "m")
    with pytest.raises(ProviderError) as exc:
        _run(provider.complete("s", "u"))
    assert exc.value.retryable is True and exc.value.status == 429

    canned = _CannedHTTP([("chat/completions", 400, {"error": "bad request"})])
    monkeypatch.setattr(module.httpx, "AsyncClient", canned)
    with pytest.raises(ProviderError) as exc:
        _run(provider.complete("s", "u"))
    assert exc.value.retryable is False


def test_gigachat_token_cache(monkeypatch):
    from src.providers.llm import gigachat as module

    canned = _CannedHTTP([
        ("ngw.devices", 200, {"access_token": "tok-1", "expires_in": 1800}),
        ("chat/completions", 200, {"model": "GigaChat-Max",
                                   "choices": [{"message": {"content": "ok"}}]}),
        ("chat/completions", 200, {"model": "GigaChat-Max",
                                   "choices": [{"message": {"content": "ok2"}}]}),
    ])
    monkeypatch.setattr(module.httpx, "AsyncClient", canned)
    provider = module.GigaChatProvider("auth-key")
    first = _run(provider.complete("s", "u"))
    second = _run(provider.complete("s", "u"))
    assert first.text == "ok" and second.text == "ok2"
    oauth_calls = sum(1 for c in canned.calls if "ngw.devices" in c["url"])
    assert oauth_calls == 1  # токен закэширован
