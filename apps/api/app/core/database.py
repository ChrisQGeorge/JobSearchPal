"""Async SQLAlchemy engine and session factory."""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    settings.async_database_url,
    # pool_pre_ping=True is broken on aiomysql: SQLAlchemy's PyMySQL
    # dialect calls the *sync* `.ping()` signature on the async
    # connection adapter, which raises:
    #   TypeError: AsyncAdapt_aiomysql_connection.ping() missing 1
    #   required positional argument: 'reconnect'
    # Triggered intermittently on connection checkout, every other
    # request 500s and the HealthGate flickers as a result. Disable
    # it and rely on pool_recycle to drop stale connections instead.
    pool_pre_ping=False,
    pool_recycle=3600,  # MySQL's default wait_timeout is 8h — recycle hourly
    pool_size=10,
    max_overflow=10,
    echo=False,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
