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
    # Bumped from 10+10 → 20+20. Streaming endpoints used to hold a pool
    # connection for the whole stream lifetime via Depends(get_db); we've
    # since moved them onto a self-managed session pattern, but the
    # larger margin gives a backstop for any new endpoint that
    # accidentally repeats the old mistake. With a single-user app this
    # is still cheap.
    pool_size=20,
    max_overflow=20,
    pool_timeout=10,  # was 30 — fail faster so the symptom is visible
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
