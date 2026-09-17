"""Dharma Engine — детерминированный слой политик ВНЕ LLM (SPEC S1-06).

LLM предлагает — Dharma разрешает: allow | deny | require_approval.
"""

from .compiler import build_default_policy, compile_policy, compile_yaml
from .ctx import TxContext
from .dsl import CompiledPolicy, PolicyError
from .evaluator import DenyReason, Verdict, VerdictDecision, evaluate

__all__ = [
    "CompiledPolicy",
    "DenyReason",
    "PolicyError",
    "TxContext",
    "Verdict",
    "VerdictDecision",
    "build_default_policy",
    "compile_policy",
    "compile_yaml",
    "evaluate",
]
