"""Репозитории KARTA (SPEC S2-01): доступ к данным без ORM-деталей в API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, Approval, Decision, Policy, Transaction, User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, username: str, password_hash: str, role: str = "user") -> User:
        user = User(username=username, password_hash=password_hash, role=role)
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_by_username(self, username: str) -> Optional[User]:
        result = await self.session.execute(sa.select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        return await self.session.get(User, user_id)

    async def update_password_hash(self, user: User, new_hash: str) -> None:
        user.password_hash = new_hash
        await self.session.flush()


class AgentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, owner_id: uuid.UUID, *, name: str, description: str = "",
                     strategy: str = "default", chain_id: int = 1,
                     wallet_address: str | None = None, config: dict | None = None,
                     status: str = "created", tier: int = 0) -> Agent:
        agent = Agent(owner_id=owner_id, name=name, description=description,
                      strategy=strategy, chain_id=chain_id, wallet_address=wallet_address,
                      config=config or {}, status=status, tier=tier)
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def get(self, agent_id: uuid.UUID) -> Optional[Agent]:
        return await self.session.get(Agent, agent_id)

    async def list_by_owner(self, owner_id: uuid.UUID, offset: int = 0,
                            limit: int = 50) -> Sequence[Agent]:
        result = await self.session.execute(
            sa.select(Agent).where(Agent.owner_id == owner_id)
            .order_by(Agent.created_at.desc()).offset(offset).limit(limit)
        )
        return result.scalars().all()

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.session.execute(
            sa.select(sa.func.count()).select_from(Agent).where(Agent.owner_id == owner_id)
        )
        return int(result.scalar_one())

    async def count_running(self) -> int:
        result = await self.session.execute(
            sa.select(sa.func.count()).select_from(Agent).where(Agent.status == "running")
        )
        return int(result.scalar_one())

    async def set_status(self, agent: Agent, status: str) -> Agent:
        agent.status = status
        agent.updated_at = _utcnow()
        await self.session.flush()
        return agent

    async def set_tier(self, agent: Agent, tier: int) -> Agent:
        agent.tier = tier
        agent.updated_at = _utcnow()
        await self.session.flush()
        return agent

    async def set_goal(self, agent: Agent, goal_text: str, context: str | None = None) -> Agent:
        agent.goal_text = goal_text
        agent.goal_structured = {"context": context} if context else None
        agent.updated_at = _utcnow()
        await self.session.flush()
        return agent


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_agent(self, agent_id: uuid.UUID, offset: int = 0,
                             limit: int = 50) -> Sequence[Transaction]:
        result = await self.session.execute(
            sa.select(Transaction).where(Transaction.agent_id == agent_id)
            .order_by(Transaction.created_at.desc()).offset(offset).limit(limit)
        )
        return result.scalars().all()

    async def count_for_agent(self, agent_id: uuid.UUID) -> int:
        result = await self.session.execute(
            sa.select(sa.func.count()).select_from(Transaction)
            .where(Transaction.agent_id == agent_id)
        )
        return int(result.scalar_one())


class DecisionRepository:
    """Decision Diary (S2-02): тезис ДО — запись каждого решения агента."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, agent_id: uuid.UUID, *, action: str, params: dict | None = None,
                  goal: str | None = None, reasoning: str | None = None,
                  alternatives: list | None = None, confidence: float | None = None,
                  risk_level: str | None = None, risk_score: float | None = None,
                  policy_verdict: dict | None = None,
                  requires_approval: bool = False,
                  status: str = "proposed") -> Decision:
        decision = Decision(
            agent_id=agent_id, action=action, params=params or {}, goal=goal,
            reasoning=reasoning, alternatives=alternatives, confidence=confidence,
            risk_level=risk_level, risk_score=risk_score,
            policy_verdict=policy_verdict, requires_approval=requires_approval,
            status=status, data_as_of=_utcnow(),
        )
        self.session.add(decision)
        await self.session.flush()
        return decision

    async def list_for_agent(self, agent_id: uuid.UUID, offset: int = 0,
                             limit: int = 50) -> Sequence[Decision]:
        result = await self.session.execute(
            sa.select(Decision).where(Decision.agent_id == agent_id)
            .order_by(Decision.created_at.desc()).offset(offset).limit(limit)
        )
        return result.scalars().all()

    async def count_for_agent(self, agent_id: uuid.UUID) -> int:
        result = await self.session.execute(
            sa.select(sa.func.count()).select_from(Decision)
            .where(Decision.agent_id == agent_id)
        )
        return int(result.scalar_one())

    async def get(self, decision_id: uuid.UUID) -> Optional[Decision]:
        return await self.session.get(Decision, decision_id)


class PolicyRepository:
    """Версионированные Dharma-политики агента (S3-01)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self, agent_id: uuid.UUID) -> Optional[Policy]:
        result = await self.session.execute(
            sa.select(Policy).where(Policy.agent_id == agent_id, Policy.active.is_(True))
            .order_by(Policy.version.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_versions(self, agent_id: uuid.UUID) -> Sequence[Policy]:
        result = await self.session.execute(
            sa.select(Policy).where(Policy.agent_id == agent_id)
            .order_by(Policy.version.desc())
        )
        return result.scalars().all()

    async def create_version(self, agent_id: uuid.UUID, dsl_yaml: str,
                             compiled: dict) -> Policy:
        """Деактивирует прежнюю версию, создаёт новую (version+1)."""
        await self.session.execute(
            sa.update(Policy)
            .where(Policy.agent_id == agent_id, Policy.active.is_(True))
            .values(active=False)
        )
        versions = await self.list_versions(agent_id)
        next_version = (versions[0].version + 1) if versions else 1
        policy = Policy(agent_id=agent_id, version=next_version,
                        dsl_yaml=dsl_yaml, compiled=compiled, active=True)
        self.session.add(policy)
        await self.session.flush()
        return policy


class ApprovalRepository:
    """Одобрения решений (web/telegram/api). Telegram не обходит policy (S4-06)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, decision_id: uuid.UUID | None = None, *,
                     channel: str = "web", ttl_minutes: int = 30) -> Approval:
        approval = Approval(
            decision_id=decision_id,
            channel=channel,
            status="pending",
            ttl_until=_utcnow().replace(microsecond=0) + __import__("datetime").timedelta(minutes=ttl_minutes),
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def get(self, approval_id: uuid.UUID) -> Optional[Approval]:
        return await self.session.get(Approval, approval_id)

    async def list_pending_with_decision(self, owner_id: uuid.UUID):
        """(Approval, Decision, Agent) для pending-одобрений агентов владельца."""
        stmt = (
            sa.select(Approval, Decision, Agent)
            .join(Decision, Approval.decision_id == Decision.id)
            .join(Agent, Decision.agent_id == Agent.id)
            .where(Approval.status == "pending", Agent.owner_id == owner_id)
            .order_by(Approval.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def resolve(self, approval_id: uuid.UUID, status: str, *,
                      decided_by: uuid.UUID | None = None,
                      comment: str | None = None) -> Optional[Approval]:
        approval = await self.session.get(Approval, approval_id)
        if approval is None or approval.status != "pending":
            return None
        approval.status = status
        approval.decided_by = decided_by
        approval.comment = comment
        approval.resolved_at = _utcnow()
        await self.session.flush()
        return approval
