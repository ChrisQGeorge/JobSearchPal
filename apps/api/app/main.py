"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_credentials as api_credentials_router
from app.api.v1 import auth as auth_router
from app.api.v1 import auth_claude as auth_claude_router
from app.api.v1 import auto_apply as auto_apply_router
from app.api.v1 import browser as browser_router
from app.api.v1 import companion as companion_router
from app.api.v1 import cover_letter_library as cover_letter_library_router
from app.api.v1 import documents as documents_router
from app.api.v1 import email_ingest as email_ingest_router
from app.api.v1 import history as history_router
from app.api.v1 import jobs as jobs_router
from app.api.v1 import organizations as organizations_router
from app.api.v1 import personas as personas_router
from app.api.v1 import preferences as preferences_router
from app.api.v1 import data_io as data_io_router
from app.api.v1 import metrics as metrics_router
from app.api.v1 import autofill as autofill_router
from app.api.v1 import resume_ingest as resume_ingest_router
from app.api.v1 import sources as sources_router
from app.core.config import settings
from app.skills.queue_worker import run_forever as run_queue_worker
from app.skills.auto_apply import run_forever as run_auto_apply_poller
from app.sources.poller import run_forever as run_source_poller

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Launch the background JobFetchQueue worker. Single task, single
    # container — if we ever scale out we'll need real coordination.
    task = asyncio.create_task(run_queue_worker(), name="job-fetch-queue")
    poller_task = asyncio.create_task(run_source_poller(), name="source-poller")
    auto_apply_task = asyncio.create_task(
        run_auto_apply_poller(), name="auto-apply-poller"
    )
    log.info(
        "Started job-fetch-queue + source-poller + auto-apply-poller background workers"
    )
    try:
        yield
    finally:
        for t in (task, poller_task, auto_apply_task):
            t.cancel()
        for t in (task, poller_task, auto_apply_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


app = FastAPI(
    title="Job Search Pal API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# Accept any origin on the loopback or RFC1918 private networks, or *.local mDNS
# names. Covers localhost, 10.x, 172.16-31.x, 192.168.x, and e.g. "mymachine.local".
# Public origins are intentionally excluded; front the deployment with a reverse
# proxy if you need to serve beyond the LAN.
LAN_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost(:\d+)?|"
    r"127\.0\.0\.1(:\d+)?|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}(:\d+)?|"
    r"192\.168\.\d{1,3}\.\d{1,3}(:\d+)?|"
    r"[a-zA-Z0-9-]+\.local(:\d+)?"
    r")$"
)

# Extra explicit origins (comma-separated env var). Useful when hosting on a
# server whose hostname / public IP isn't covered by the LAN regex.
_extra_origins = [
    o.strip()
    for o in (settings.EXTRA_CORS_ORIGINS or "").split(",")
    if o.strip()
]

if settings.ALLOW_ALL_ORIGINS:
    # Wildcard-plus-credentials isn't allowed by spec, so use a regex that
    # matches everything but still lets credentials pass through.
    log.warning("ALLOW_ALL_ORIGINS=true — CORS is wide open. Dev only.")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LAN_ORIGIN_REGEX,
        allow_origins=_extra_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.APP_ENV}


@app.get("/health/claude", tags=["health"])
async def claude_health() -> dict[str, object]:
    """Reports whether the Claude Code CLI is reachable and authenticated inside the container."""
    from app.skills.runner import claude_is_available
    from app.skills.token_store import has_token

    available = await claude_is_available()
    has_stored_token = has_token()
    has_api_key = bool(settings.ANTHROPIC_API_KEY)

    return {
        "claude_cli_available": available,
        "cli_bin": settings.CLAUDE_CODE_BIN,
        "has_anthropic_api_key": has_api_key,
        "has_oauth_session": has_stored_token,
        "authenticated": has_stored_token or has_api_key,
        "login_hint": "Use the Companion page's Launch OAuth login button.",
    }


app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(auth_claude_router.router, prefix="/api/v1")
app.include_router(api_credentials_router.router, prefix="/api/v1")
app.include_router(history_router.router, prefix="/api/v1")
app.include_router(organizations_router.router, prefix="/api/v1")
app.include_router(jobs_router.router, prefix="/api/v1")
app.include_router(documents_router.router, prefix="/api/v1")
app.include_router(personas_router.router, prefix="/api/v1")
app.include_router(preferences_router.router, prefix="/api/v1")
app.include_router(data_io_router.router, prefix="/api/v1")
app.include_router(metrics_router.router, prefix="/api/v1")
app.include_router(autofill_router.router, prefix="/api/v1")
app.include_router(resume_ingest_router.router, prefix="/api/v1")
app.include_router(companion_router.router, prefix="/api/v1")
app.include_router(cover_letter_library_router.router, prefix="/api/v1")
app.include_router(email_ingest_router.router, prefix="/api/v1")
app.include_router(auto_apply_router.router, prefix="/api/v1")
sources_router.register(app)
browser_router.register(app)
