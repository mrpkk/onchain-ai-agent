"""Database engine/session (SPEC S2-01): async SQLAlchemy, PG в проде, SQLite в тестах."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config.settings import get_settings
from .models import Base

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


def reset_engine() -> None:
    """Сброс кэша engine/sessionmaker (используется в тестах и при реконфигурации)."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


async def create_all() -> None:
    """Создать таблицы (для тестов и первого локального запуска; прод — Alembic)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Транзакционная сессия: commit при успехе, rollback при ошибке."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
