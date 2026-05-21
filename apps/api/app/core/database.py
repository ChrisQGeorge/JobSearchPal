"""Async SQLAlchemy engine and session factory.

Pool sizing note: this used to use the default QueuePool with size 10
(then 20, then 50). It kept exhausting. The root cause was structural,
not numeric — every FastAPI endpoint with `Depends(get_db)` pins a
pool connection for the ENTIRE request duration, including the
30–180 s window when the handler is sitting inside an `await
run_claude_prompt(...)` call. With ~165 such endpoints, no fixed pool
size survives bursty traffic. Auditing every endpoint to release its
session before Claude calls is doable but tedious and easy to regress.

So we use `NullPool` instead. Each session opens a fresh MySQL
connection on first use and closes it on session exit. No pool, no
ceiling — the only cap is MySQL's `max_connections` (bumped to 500
in docker-compose.yml). The cost is ~5–10 ms per request for the
TCP + auth handshake against localhost MySQL, which is unnoticeable
in this single-user, container-local setup. If we ever need to
optimize this back, the right move is to switch the Claude-calling
endpoints to a self-managed-session pattern (a few have already been
converted; see perform_fetch, queue_worker._handle_fetch, the SSE
endpoints) rather than re-introduce a fixed-size pool.
"""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(
    settings.async_database_url,
    poolclass=NullPool,
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
