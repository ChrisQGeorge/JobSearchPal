"""Async SQLAlchemy engine and session factory.

Pooling history (because it took several iterations):
  - Original 10+10 QueuePool exhausted because endpoints calling Claude
    held their dep-injected session for the full 30–180 s Claude call.
  - Bumping to 50+50 just delayed the exhaustion under burst load.
  - NullPool removed the QueuePool errors but created a new problem:
    every request opened a fresh MySQL connection, every handler ran a
    little slower, and Node's HTTP keepalive agent caught stale sockets
    after uvicorn's 5 s idle close, producing ECONNRESETs on the tracker
    page (which fans out 4–5 parallel requests at once).

What's here now: a modest QueuePool. The real connection-leak culprits
(perform_fetch + queue_worker._handle_fetch + the SSE endpoints) were
already converted to self-managed sessions in earlier commits, so the
pool actually gets reused properly now. 15+15=30 is plenty for a
single-user app — and we're also adding a consolidated /jobs/tracker-view
endpoint so the tracker page stops fanning out parallel requests.

Liveness: pool_pre_ping is ON. If MySQL restarts (e.g. the host OOM-kills
it under load — the parallel Claude CLIs + a big query can spike memory),
every connection already in the pool is now dead. Without pre-ping the
pool keeps handing those dead sockets out and every request fails with
"Lost connection to MySQL server during query" until pool_recycle finally
ages them out — a cascade that doesn't self-heal for up to an hour. With
pre-ping, SQLAlchemy issues a cheap liveness check on checkout, silently
discards a dead connection, and opens a fresh one. A prior comment here
claimed pre-ping was "broken on aiomysql"; that wasn't borne out by the
documented history (which is about NullPool vs QueuePool) and it works
correctly on SQLAlchemy 2.0's async engine.
"""
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
    # Validate each pooled connection on checkout so a MySQL restart can't
    # poison the pool with dead sockets (see module docstring).
    pool_pre_ping=True,
    # Recycle well under MySQL's wait_timeout so long-idle connections are
    # refreshed proactively, not just caught by pre-ping.
    pool_recycle=1800,
    pool_size=15,
    max_overflow=15,
    pool_timeout=10,
    # LIFO keeps a small set of connections hot and lets the rest go idle
    # so MySQL can reap them — fewer stale sockets lingering in the pool.
    pool_use_lifo=True,
    # Don't let a wedged / restarting MySQL block a connection attempt
    # indefinitely; fail fast so pre-ping can retry with a fresh socket.
    connect_args={"connect_timeout": 10},
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
