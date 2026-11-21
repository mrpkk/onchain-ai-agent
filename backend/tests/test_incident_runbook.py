"""Инцидент-ранбук: каждая команда и адрес в нём существуют в коде.

22.11.2026: возврат был описан, инцидент — нет. Хуже выдуманного ранбука нет:
человек в аварии идёт по шагам и находит, что ручки не существует.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_kill_switch_endpoint_exists():
    runbook = _read("docs/INCIDENT-RUNBOOK.md")
    api = _read("backend/src/api/main.py")
    assert "/kill-switch" in runbook
    assert '@app.post("/api/v1/agents/{agent_id}/kill-switch"' in api


def test_killed_agent_is_refused_with_409():
    """Остановка должна быть проверяемой: следующее действие получает 409."""
    runbook = _read("docs/INCIDENT-RUNBOOK.md")
    api = _read("backend/src/api/main.py")
    assert "409" in runbook and "killed" in runbook.lower()
    assert 'status_code=409, detail="Agent has been killed"' in api


def test_evidence_endpoint_exists():
    assert "/evidence" in _read("docs/INCIDENT-RUNBOOK.md")
    assert '@app.get("/api/v1/agents/{agent_id}/evidence")' in _read("backend/src/api/main.py")


def test_audit_log_is_named_the_same_way():
    """Ранбук говорит `Sakshi Log` — значит и в коде событие пишется тем же журналом."""
    runbook = _read("docs/INCIDENT-RUNBOOK.md")
    api = _read("backend/src/api/main.py")
    assert "Sakshi Log" in runbook
    assert "SakshiLog" in api and 'event_type="kill_switch"' in api


def test_runbook_covers_severity_and_comms():
    runbook = _read("docs/INCIDENT-RUNBOOK.md")
    for needle in ("S1", "S2", "S3", "S4", "Subject:", "Evidence:", "Что changes".replace("Что ", "")):
        assert needle in runbook, needle
    assert "REFUND-RUNBOOK.md" in runbook      # связь с возвратом, а не два раздельных мира


def test_runbook_promises_a_test_per_incident():
    """Инцидент без нового теста считается незакрытым — это правило, а не лозунг."""
    assert "без нового теста" in _read("docs/INCIDENT-RUNBOOK.md")
