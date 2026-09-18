"""Репозитории KARTA (SPEC S2-01): доступ к данным без ORM-деталей в API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, Transaction, User


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
                     status: str = "created") -> Agent:
        agent = Agent(owner_id=owner_id, name=name, description=description,
                      strategy=strategy, chain_id=chain_id, wallet_address=wallet_address,
                      config=config or {}, status=status)
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
