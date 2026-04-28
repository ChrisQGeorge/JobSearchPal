"""Cover-letter snippet library — reusable hooks, bridges, and closes the
user keeps on file. The tailor / Companion can pull a few in by kind/tag
when drafting cover letters so the model isn't inventing fresh openers
every time. Pure CRUD; no Claude calls live here."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.documents import CoverLetterSnippet
from app.models.user import User

router = APIRouter(prefix="/cover-letter-library", tags=["cover-letter-library"])


# Free-form by design — the user can invent their own buckets — but we
# pre-seed a short list for the dropdown UI. Anything outside this list is
# accepted; the UI just won't auto-suggest it.
KNOWN_KINDS = {"hook", "bridge", "close", "anecdote", "value_prop", "other"}


class SnippetIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=255)
    content_md: str = Field(min_length=1)
    tags: Optional[list[str]] = None


class SnippetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    title: str
    content_md: str
    tags: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime


def _normalize_tags(tags: Optional[list[str]]) -> Optional[list[str]]:
    if tags is None:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        s = str(t).strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s[:64])
    return out


async def _owned(db: AsyncSession, snippet_id: int, user_id: int) -> CoverLetterSnippet:
    row = (
        await db.execute(
            select(CoverLetterSnippet).where(
                CoverLetterSnippet.id == snippet_id,
                CoverLetterSnippet.user_id == user_id,
                CoverLetterSnippet.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return row


@router.get("", response_model=list[SnippetOut])
async def list_snippets(
    kind: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CoverLetterSnippet]:
    stmt = (
        select(CoverLetterSnippet)
        .where(
            CoverLetterSnippet.user_id == user.id,
            CoverLetterSnippet.deleted_at.is_(None),
        )
        .order_by(CoverLetterSnippet.kind, CoverLetterSnippet.created_at.desc())
    )
    if kind:
        stmt = stmt.where(CoverLetterSnippet.kind == kind)
    rows = list((await db.execute(stmt)).scalars().all())
    if tag:
        t = tag.strip().lower()
        rows = [r for r in rows if t in (r.tags or [])]
    return rows


@router.post("", response_model=SnippetOut, status_code=status.HTTP_201_CREATED)
async def create_snippet(
    payload: SnippetIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CoverLetterSnippet:
    snippet = CoverLetterSnippet(
        user_id=user.id,
        kind=payload.kind.strip().lower()[:32],
        title=payload.title.strip()[:255],
        content_md=payload.content_md,
        tags=_normalize_tags(payload.tags),
    )
    db.add(snippet)
    await db.commit()
    await db.refresh(snippet)
    return snippet


class SnippetUpdate(BaseModel):
    kind: Optional[str] = Field(default=None, min_length=1, max_length=32)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content_md: Optional[str] = None
    tags: Optional[list[str]] = None


@router.put("/{snippet_id:int}", response_model=SnippetOut)
async def update_snippet(
    snippet_id: int,
    payload: SnippetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CoverLetterSnippet:
    row = await _owned(db, snippet_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    if "kind" in data and data["kind"] is not None:
        data["kind"] = str(data["kind"]).strip().lower()[:32]
    if "title" in data and data["title"] is not None:
        data["title"] = str(data["title"]).strip()[:255]
    if "tags" in data:
        data["tags"] = _normalize_tags(data["tags"])
    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{snippet_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_snippet(
    snippet_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = await _owned(db, snippet_id, user.id)
    row.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


@router.get("/kinds", response_model=list[str])
async def list_known_kinds() -> list[str]:
    """Suggested `kind` values for the UI dropdown. Free-form on the API
    side — anything is accepted on create — but these are the buckets the
    library page surfaces by default."""
    return sorted(KNOWN_KINDS)
