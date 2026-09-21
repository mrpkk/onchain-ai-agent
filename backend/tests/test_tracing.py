"""Тесты S2-06: трейсинг решений — request_id, agent_id, prompt-version, cost."""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.reasoning import PROMPT_VERSION, LLMReasoner  # noqa: E402
from src.observability.tracer import estimate_cost, new_request_id  # noqa: E402
from src.providers.llm import LLMProvider, LLMResult, LLMRouter  # noqa: E402
from tests.test_llm_router import EchoSchema, ScriptedProvider  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_new_request_id_unique():
    assert new_request_id() != new_request_id()


def test_estimate_cost_from_env(monkeypatch):
    monkeypatch.setenv("KARTA_PRICE_DEEPSEEK_IN", "0.14")
    monkeypatch.setenv("KARTA_PRICE_DEEPSEEK_OUT", "0.28")
    cost = estimate_cost("deepseek", 1000, 500)
    assert cost == pytest_approx(0.28)
    assert estimate_cost("deepseek", None, None) is None


def pytest_approx(value):
    import pytest
    return pytest.approx(value, rel=1e-6)


def test_estimate_cost_without_prices_is_none(monkeypatch):
    monkeypatch.delenv("KARTA_PRICE_UNKNOWN_IN", raising=False)
    monkeypatch.delenv("KARTA_PRICE_UNKNOWN_OUT", raising=False)
    assert estimate_cost("unknown", 100, 100) is None


def test_router_trace_on_success(caplog):
    provider = ScriptedProvider("scripted", ['{"value": 1}'])
    router = LLMRouter([provider])
    with caplog.at_level(logging.INFO, logger="karta.trace"):
        parsed, result = _run(router.complete_json(
            "s", "u", EchoSchema, agent_id="agent_test", prompt_version=PROMPT_VERSION))
    assert parsed.value == 1
    assert result.request_id
    trace = next(r.message for r in caplog.records if "llm_trace" in r.message)
    assert '"agent_id": "agent_test"' in trace
    assert f'"prompt_version": "{PROMPT_VERSION}"' in trace
    assert '"provider": "scripted"' in trace
    assert '"ok": true' in trace


def test_router_trace_on_total_failure(caplog):
    from src.providers.llm import ProviderError

    provider = ScriptedProvider("dead", [ProviderError("net", retryable=False)])
    router = LLMRouter([provider])
    with caplog.at_level(logging.INFO, logger="karta.trace"):
        try:
            _run(router.complete_json("s", "u", EchoSchema, agent_id="agent_x",
                                      prompt_version=PROMPT_VERSION))
        except Exception:
            pass
    trace = next(r.message for r in caplog.records if "llm_trace" in r.message)
    assert '"ok": false' in trace
    assert '"provider": "none"' in trace


def test_reasoner_passes_agent_id(caplog):
    provider = ScriptedProvider("good", [
        '{"action": "hold", "params": {}, "reasoning": "r", "confidence": 0.5, '
        '"risk_level": "low", "estimated_gas": 0, "requires_approval": false}',
    ])
    reasoner = LLMReasoner(router=LLMRouter([provider]), agent_id="agent_42")
    with caplog.at_level(logging.INFO, logger="karta.trace"):
        decision = _run(reasoner.decide(state={}, goal="test"))
    assert decision.action == "hold"
    trace = next(r.message for r in caplog.records if "llm_trace" in r.message)
    assert '"agent_id": "agent_42"' in trace
