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
    # pool_pre_ping=True is broken on aiomysql — see history above.
    pool_pre_ping=False,
    pool_recycle=3600,  # MySQL wait_timeout default is 8 h; recycle hourly.
    pool_size=15,
    max_overflow=15,
    pool_timeout=10,
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
