"""Descriptive errors for every API response.

Every request gets a short request id (X-Request-Id header). Every error
response — HTTPException, validation error, or an unhandled crash —
has the same JSON shape:

    {"detail": <unchanged, for existing callers>,
     "error": {"code": "DB_POOL_EXHAUSTED",
               "message": "TimeoutError: QueuePool limit of size 15 ...",
               "hint": "Too many database connections are in use ...",
               "request_id": "a1b2c3d4",
               "path": "GET /api/v1/jobs"}}

Unhandled exceptions are classified into specific codes (pool exhausted,
database unreachable, upstream timeout, Jev / LLM errors, response
validation, …) with a plain-English hint, and logged with the request id
and full traceback so `docker logs jsp-api | grep <request_id>` finds it.
Requests slower than SLOW_REQUEST_SECONDS are logged too.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("jsp.errors")

SLOW_REQUEST_SECONDS = 3.0
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "INVALID_INPUT",
    429: "RATE_LIMITED",
    501: "NOT_IMPLEMENTED",
    502: "UPSTREAM_ERROR",
    503: "SERVICE_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}


def _rid(request: Request) -> str:
    # Read from the ASGI scope: Starlette's catch-all handler runs OUTSIDE
    # our middleware, after its context var has been reset.
    return (request.scope.get("state") or {}).get("request_id") or request_id_var.get()


def _body(code: str, message: str, request: Request, hint: str | None = None,
          detail: Any = None) -> dict:
    return {
        "detail": detail if detail is not None else message,
        "error": {
            "code": code,
            "message": message,
            "hint": hint,
            "request_id": _rid(request),
            "path": f"{request.method} {request.url.path}",
        },
    }


def classify(exc: BaseException) -> tuple[int, str, str]:
    """(status, code, hint) for an unhandled exception."""
    name = type(exc).__name__
    mod = type(exc).__module__ or ""
    text = str(exc)
    if mod.startswith("sqlalchemy") and name == "TimeoutError":
        return 503, "DB_POOL_EXHAUSTED", (
            "Every database connection was busy for 10s. Background tasks may be "
            "saturating the pool — check /health/deep (pools, queue) and "
            "`docker logs jsp-api`."
        )
    if mod.startswith("sqlalchemy") and name in ("OperationalError", "InterfaceError", "DisconnectionError"):
        return 503, "DB_UNAVAILABLE", (
            "The API couldn't talk to MySQL (restarting, out of memory, or "
            "connection dropped). Check `docker ps` / `docker logs jsp-db`."
        )
    if mod.startswith("sqlalchemy") and name == "IntegrityError":
        return 409, "DB_CONFLICT", "The write conflicted with existing data (duplicate or missing reference)."
    if mod.startswith("sqlalchemy") and name == "DataError":
        return 400, "DB_DATA_ERROR", "A value didn't fit its database column (too long / wrong type)."
    if mod.startswith("sqlalchemy"):
        return 500, "DB_ERROR", "Unexpected database error — see the server log for this request id."
    if isinstance(exc, asyncio.TimeoutError) or name in ("TimeoutException", "ReadTimeout", "ConnectTimeout"):
        return 504, "UPSTREAM_TIMEOUT", "An outside service (Jev, an LLM, a job site) didn't answer in time."
    if mod.startswith("httpx"):
        return 502, "UPSTREAM_ERROR", "An outside service request failed (network / DNS / bad response)."
    if name == "JevError":
        status = 429 if " 429" in text else 502
        return status, "JEV_ERROR", "TypeSafe Jev returned an error — check the API key in Settings → API Keys."
    if name == "ClaudeCodeError":
        return 502, "LLM_ERROR", "The Claude / LLM call failed — check Settings → Claude Auth or the model provider."
    if name == "ValidationError" and mod.startswith("pydantic"):
        return 500, "RESPONSE_VALIDATION", (
            "Stored data didn't fit the response shape (a field has an unexpected "
            "value). The server log lists the offending field."
        )
    if isinstance(exc, (PermissionError, FileNotFoundError, OSError)):
        return 500, "FILESYSTEM_ERROR", "A file the server needs couldn't be read or written."
    return 500, "INTERNAL_ERROR", "Unexpected server error — see the server log for this request id."


class RequestContext:
    """ASGI middleware: request id, X-Request-Id header, slow-request log.
    Pure ASGI (not BaseHTTPMiddleware) so streaming responses pass through."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid.uuid4().hex[:8]
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)
        t0 = time.monotonic()
        status_holder = {"status": 0}

        async def _send(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            dt = time.monotonic() - t0
            path = scope.get("path", "")
            if dt > SLOW_REQUEST_SECONDS and "/stream" not in path:
                log.warning(
                    "SLOW request %s %s %.1fs status=%s rid=%s",
                    scope.get("method"), path, dt, status_holder["status"], rid,
                )
            request_id_var.reset(token)


def install(app: FastAPI) -> None:
    app.add_middleware(RequestContext)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(code, msg, request, detail=exc.detail),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError):
        problems = [
            f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg')}"
            for e in exc.errors()[:8]
        ]
        return JSONResponse(
            status_code=422,
            content=_body(
                "INVALID_INPUT",
                "Request didn't validate — " + "; ".join(problems),
                request,
                hint="The app sent a value the API doesn't accept.",
                detail=exc.errors(),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        status, code, hint = classify(exc)
        message = f"{type(exc).__name__}: {str(exc)[:400]}"
        log.exception(
            "Unhandled %s on %s %s rid=%s", code, request.method, request.url.path, _rid(request),
        )
        return JSONResponse(
            status_code=status,
            content=_body(code, message, request, hint=hint),
            headers={"x-request-id": _rid(request)},
        )


async def deep_health() -> dict:
    """Everything worth knowing when the app feels stuck."""
    from sqlalchemy import func, select, text

    from app.core.database import SessionLocal, pool_status
    from app.core.responsiveness import background_capacity, snapshot
    from app.models.jobs import JobFetchQueue
    from app.skills import worker_settings

    out: dict[str, Any] = {"responsiveness": snapshot(), "db_pools": pool_status()}
    t0 = time.monotonic()
    try:
        async with SessionLocal() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=5)
            out["db_ping_ms"] = round((time.monotonic() - t0) * 1000, 1)
            rows = (
                await db.execute(
                    select(JobFetchQueue.kind, JobFetchQueue.state, func.count(JobFetchQueue.id))
                    .where(JobFetchQueue.state.in_(("queued", "processing", "error")))
                    .group_by(JobFetchQueue.kind, JobFetchQueue.state)
                )
            ).all()
            queue: dict[str, dict[str, int]] = {}
            for kind, state, n in rows:
                queue.setdefault(kind or "fetch", {})[state] = n
            out["queue"] = queue
    except Exception as exc:  # noqa: BLE001
        status, code, hint = classify(exc)
        out["db_error"] = {"code": code, "message": f"{type(exc).__name__}: {exc}"[:300], "hint": hint}
    configured = worker_settings.get_max_parallel()
    out["worker"] = {
        "max_parallel_setting": configured,
        "effective_parallel_now": background_capacity(configured),
    }
    out["memory"] = _memory()
    return out


def _memory() -> dict:
    def _read(path: str) -> str | None:
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return None

    mem: dict[str, Any] = {}
    status = _read("/proc/self/status") or ""
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            mem["api_process_rss_mb"] = round(int(line.split()[1]) / 1024, 1)
    cur, limit = _read("/sys/fs/cgroup/memory.current"), _read("/sys/fs/cgroup/memory.max")
    if cur and cur.isdigit():
        mem["container_used_mb"] = round(int(cur) / 1048576, 1)
    if limit and limit.isdigit():
        mem["container_limit_mb"] = round(int(limit) / 1048576, 1)
        if "container_used_mb" in mem:
            mem["container_used_pct"] = round(100 * mem["container_used_mb"] / mem["container_limit_mb"], 1)
    return mem
