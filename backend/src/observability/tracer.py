"""Трейсинг решений KARTA (SPEC S2-06).

Структурные логи LLM-вызовов: request_id, agent_id, provider, model, latency,
tokens, cost (только из env-прайса — не выдумываем), prompt_version.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger("karta.trace")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def estimate_cost(provider: str, tokens_in: Optional[int], tokens_out: Optional[int]) -> Optional[float]:
    """Стоимость в USD, если заданы цены (за 1k токенов) в env; иначе None.

    Env: KARTA_PRICE_<PROVIDER>_IN / KARTA_PRICE_<PROVIDER>_OUT.
    """
    if tokens_in is None and tokens_out is None:
        return None
    price_in = os.getenv(f"KARTA_PRICE_{provider.upper()}_IN")
    price_out = os.getenv(f"KARTA_PRICE_{provider.upper()}_OUT")
    if price_in is None and price_out is None:
        return None
    try:
        cost = 0.0
        if tokens_in is not None and price_in is not None:
            cost += (tokens_in / 1000.0) * float(price_in)
        if tokens_out is not None and price_out is not None:
            cost += (tokens_out / 1000.0) * float(price_out)
        return round(cost, 6)
    except ValueError:
        return None


def log_llm_trace(*, request_id: str, agent_id: Optional[str], provider: str,
                  model: str, latency_ms: int, tokens_prompt: Optional[int],
                  tokens_completion: Optional[int], cost_usd: Optional[float],
                  prompt_version: str, ok: bool, error: Optional[str] = None) -> None:
    """Единая структурная строка трейса LLM-вызова."""
    payload = {
        "event": "llm_trace",
        "request_id": request_id,
        "agent_id": agent_id,
        "provider": provider,
        "model": model,
        "latency_ms": latency_ms,
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "cost_usd": cost_usd,
        "prompt_version": prompt_version,
        "ok": ok,
    }
    if error:
        payload["error"] = error[:300]
    logger.info(json.dumps(payload, ensure_ascii=False))
