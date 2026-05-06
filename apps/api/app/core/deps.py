"""FastAPI dependencies — current user resolution."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    # Auth precedence: session cookie (browser) wins, then Authorization bearer
    # header (used by the Companion subprocess to call the API on behalf of
    # the user via curl).
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
        )
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user",
        )
    return user


CurrentUser = Depends(get_current_user)


async def _resolve_user_from_request(
    request_or_ws,
    db: AsyncSession,
) -> User | None:
    """WebSocket-friendly auth resolver. The standard get_current_user
    dependency is HTTP-only because it raises HTTPException; this
    variant returns None so the caller can `await ws.close()`.

    Accepts either an `fastapi.Request` or a `fastapi.WebSocket` —
    both expose `.cookies` and `.headers` the same way."""
    token = request_or_ws.cookies.get(settings.COOKIE_NAME)
    if not token:
        # WebSockets sometimes pass auth via subprotocol or query
        # string. Cookie is the primary path; we support a `?token=`
        # fallback for browsers that strip cookies on cross-origin
        # WebSocket upgrades.
        try:
            qs_token = request_or_ws.query_params.get("token")
        except Exception:
            qs_token = None
        if qs_token:
            token = qs_token
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()
