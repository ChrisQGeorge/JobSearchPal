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
"Lost connection to MySQL server during query". With pre-ping, SQLAlchemy
issues a cheap liveness check on checkout, silently discards a dead
connection, and opens a fresh one.

The aiomysql ping bug (and why we override do_ping): a prior comment here
said pre-ping was "broken on aiomysql" — that part was RIGHT. SQLAlchemy's
stock MySQL `do_ping` calls `dbapi_connection.ping()` with no arguments,
but the aiomysql async adapter exposes `ping(reconnect)` with no default,
so pre-ping raised `TypeError: ping() missing 1 required positional
argument: 'reconnect'` and 500'd every DB request. We override do_ping to
pass `reconnect=False` explicitly — which is also the semantically correct
value: we want a dead connection to RAISE so SQLAlchemy recycles it, not
have aiomysql silently reconnect under the pool's feet. The try/except
covers adapter signature differences across SQLAlchemy versions.
"""
from __future__ import annotations

import types
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


def _aiomysql_do_ping(_dialect, dbapi_connection) -> bool:
    """Pre-ping liveness check that works with the aiomysql adapter.

    See module docstring: the stock do_ping calls ping() with no args,
    which the aiomysql adapter rejects. Pass reconnect=False explicitly;
    fall back to the no-arg form for adapter versions that take no param.
    A dead connection raises here, which is exactly what tells the pool to
    discard and replace it.
    """
    try:
        dbapi_connection.ping(False)
    except TypeError:
        dbapi_connection.ping()
    return True


# Bind the override onto the engine's dialect — this is the same dialect
# instance the pool consults for pre-ping (pool._dialect.do_ping).
engine.sync_engine.dialect.do_ping = types.MethodType(
    _aiomysql_do_ping, engine.sync_engine.dialect
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)

# Background work (queue worker, source poller, Gmail poller, import
# pipeline) gets its OWN, smaller pool. However many tasks run, they
# queue on this pool and can never take the connections that page loads
# and API requests use — browsing stays responsive by construction.
bg_engine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=8,
    max_overflow=4,
    # Background callers can wait for a connection; nothing user-facing
    # is blocked on them.
    pool_timeout=120,
    pool_use_lifo=True,
    connect_args={"connect_timeout": 10},
    echo=False,
)
bg_engine.sync_engine.dialect.do_ping = types.MethodType(
    _aiomysql_do_ping, bg_engine.sync_engine.dialect
)

BgSessionLocal = async_sessionmaker(
    bind=bg_engine,
    expire_on_commit=False,
    autoflush=False,
)


# ---- Who is holding connections? -------------------------------------------
#
# Every checkout is tagged with the current request ("GET /api/v1/x #rid",
# set by core.errors.RequestContext) or "background". When the web pool
# runs dry, the 503 names the longest holders, /health/deep lists them,
# and a web connection held > HOLD_WARN_SECONDS is logged at checkin —
# so the next exhaustion points straight at its cause.

import logging as _logging
import time as _time
from contextvars import ContextVar

db_holder_var: ContextVar[str] = ContextVar("db_holder", default="background")
HOLD_WARN_SECONDS = 20.0
_HOLDERS: dict[str, dict[int, tuple[str, float]]] = {"web": {}, "background": {}}
_hold_log = _logging.getLogger("app.db.holders")


def _track(name: str, eng) -> None:
    from sqlalchemy import event

    holders = _HOLDERS[name]

    @event.listens_for(eng.sync_engine.pool, "checkout")
    def _on_checkout(_dbapi, record, _proxy):  # noqa: ANN001
        holders[id(record)] = (db_holder_var.get(), _time.monotonic())

    @event.listens_for(eng.sync_engine.pool, "checkin")
    def _on_checkin(_dbapi, record):  # noqa: ANN001
        info = holders.pop(id(record), None)
        if info and name == "web":
            held = _time.monotonic() - info[1]
            if held > HOLD_WARN_SECONDS:
                _hold_log.warning(
                    "web DB connection held %.0fs by %s — commit before slow calls", held, info[0]
                )


_track("web", engine)
_track("background", bg_engine)


def connection_holders(limit: int = 10) -> dict[str, list[dict]]:
    """Current holders per pool, longest first."""
    now = _time.monotonic()
    out: dict[str, list[dict]] = {}
    for name, holders in _HOLDERS.items():
        rows = sorted(holders.values(), key=lambda t: t[1])
        out[name] = [{"by": by, "held_s": round(now - t0, 1)} for by, t0 in rows[:limit]]
    return out


def pool_status() -> dict:
    """Checked-out / idle counts for both pools (for /health/deep)."""
    out = {}
    for name, eng in (("web", engine), ("background", bg_engine)):
        p = eng.sync_engine.pool
        try:
            out[name] = {
                "size": p.size(),
                "checked_out": p.checkedout(),
                "idle": p.checkedin(),
                "overflow": p.overflow(),
            }
        except Exception:  # pragma: no cover — pool impl without stats
            out[name] = {"status": p.status()}
    return out


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
