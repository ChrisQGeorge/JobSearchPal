"""Async SQLAlchemy engine and session factory."""
from __future__ import annotations

import logging
import traceback
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

log = logging.getLogger(__name__)

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
    # Bumped to 50+50=100 max. MySQL's default max_connections is 151 so
    # this still leaves headroom for the worker / poller / direct admin
    # access. We still want to fix the underlying "session held during
    # Claude call" leak — see queue_worker + Claude-calling endpoints —
    # but the bigger pool gets the app usable while that work lands.
    pool_size=50,
    max_overflow=50,
    pool_timeout=10,
    echo=False,
)


# Pool diagnostics — logs the call site of every checkout that's
# still holding a connection when the pool is near exhaustion.
# Triggered only when pool usage crosses a warn threshold so the log
# isn't spammed in normal operation. Set JSP_POOL_DIAG=1 to enable.
import os as _os

if _os.environ.get("JSP_POOL_DIAG") == "1":
    _OPEN_CHECKOUTS: dict[int, str] = {}

    @event.listens_for(engine.sync_engine, "checkout")
    def _on_checkout(dbapi_conn, connection_record, connection_proxy):
        _OPEN_CHECKOUTS[id(connection_record)] = "".join(
            traceback.format_stack(limit=12)
        )
        total = engine.pool.checkedout()  # type: ignore[attr-defined]
        if total >= 30:
            log.warning(
                "DB pool checkout count=%d (size=%d, overflow=%d). "
                "Recent checkout stack:\n%s",
                total,
                50,
                50,
                _OPEN_CHECKOUTS[id(connection_record)],
            )

    @event.listens_for(engine.sync_engine, "checkin")
    def _on_checkin(dbapi_conn, connection_record):
        _OPEN_CHECKOUTS.pop(id(connection_record), None)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
