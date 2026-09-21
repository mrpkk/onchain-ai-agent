"""Тесты S3-04: dead-man switch — нет heartbeat N секунд → hard kill."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from src.agent.core import AgentConfig, OnChainAgent  # noqa: E402


def _agent(timeout: int = 0) -> OnChainAgent:
    return OnChainAgent(AgentConfig(name="dm-test", chain="sepolia",
                                    deadman_timeout_seconds=timeout))


def test_disabled_by_default():
    agent = _agent(timeout=0)
    agent._last_heartbeat = datetime.now(timezone.utc) - timedelta(days=1)
    assert agent._check_deadman() is False
    assert agent.state.status != "killed"


def test_fresh_heartbeat_no_kill():
    agent = _agent(timeout=3600)
    agent.heartbeat()
    assert agent._check_deadman() is False
    assert agent.state.status != "killed"


def test_expired_heartbeat_triggers_hard_kill():
    agent = _agent(timeout=3600)
    agent._last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=2)
    assert agent._check_deadman() is True
    assert agent.config.kill_switch is True
    assert agent.state.status == "killed"
    events = [e["event"] for e in agent._audit_log]
    assert "deadman_triggered" in events and "kill_switch" in events


def test_heartbeat_resets_counter():
    agent = _agent(timeout=3600)
    agent._last_heartbeat = datetime.now(timezone.utc) - timedelta(hours=2)
    agent.heartbeat()  # владелец пинганул — kill не должен сработать
    assert agent._check_deadman() is False
    assert agent.state.status != "killed"
