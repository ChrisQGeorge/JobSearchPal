"""User-managed API credentials. Currently used by the Bright Data
adapter (LinkedIn / Glassdoor scraping) but designed to host any
third-party key.

Secrets are stored encrypted via the existing AES-256-GCM helpers in
`app.core.security`. The plaintext is NEVER returned by GET endpoints —
only `last4` so the user can identify which key they have. Set a new
key via PUT (idempotent on (provider, label))."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import decrypt_secret, encrypt_secret
from app.models.user import ApiCredential, User

router = APIRouter(prefix="/auth/credentials", tags=["credentials"])


class CredentialIn(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    label: str = Field(default="default", min_length=1, max_length=255)
    secret: str = Field(min_length=1, max_length=4096)


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider: str
    label: str
    last4: str
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


def _last4(plaintext: str) -> str:
    s = plaintext.strip()
    if len(s) <= 4:
        return "*" * len(s)
    return f"…{s[-4:]}"


async def _row_to_out(row: ApiCredential) -> CredentialOut:
    try:
        plain = decrypt_secret(row.encrypted_secret)
    except Exception:
        plain = ""
    return CredentialOut(
        id=row.id,
        provider=row.provider,
        label=row.label,
        last4=_last4(plain),
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[CredentialOut])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CredentialOut]:
    rows = (
        await db.execute(
            select(ApiCredential).where(
                ApiCredential.user_id == user.id,
                ApiCredential.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return [await _row_to_out(r) for r in rows]


@router.put("", response_model=CredentialOut)
async def upsert_credential(
    payload: CredentialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialOut:
    """Create or replace the secret for `(provider, label)`. Idempotent —
    re-PUT to rotate the key without creating a second row."""
    existing = (
        await db.execute(
            select(ApiCredential).where(
                ApiCredential.user_id == user.id,
                ApiCredential.provider == payload.provider,
                ApiCredential.label == payload.label,
            )
        )
    ).scalar_one_or_none()
    encrypted = encrypt_secret(payload.secret.strip())
    if existing is None:
        existing = ApiCredential(
            user_id=user.id,
            provider=payload.provider,
            label=payload.label,
            encrypted_secret=encrypted,
        )
        db.add(existing)
    else:
        existing.encrypted_secret = encrypted
        existing.deleted_at = None
    await db.commit()
    await db.refresh(existing)
    return await _row_to_out(existing)


@router.delete("/{credential_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = (
        await db.execute(
            select(ApiCredential).where(
                ApiCredential.id == credential_id,
                ApiCredential.user_id == user.id,
                ApiCredential.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    row.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


async def get_user_secret(
    db: AsyncSession, user_id: int, provider: str, label: str = "default"
) -> Optional[str]:
    """Fetch the decrypted secret for a (provider, label). Returns None
    if no row exists. Used by source adapters."""
    row = (
        await db.execute(
            select(ApiCredential).where(
                ApiCredential.user_id == user_id,
                ApiCredential.provider == provider,
                ApiCredential.label == label,
                ApiCredential.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        plain = decrypt_secret(row.encrypted_secret)
    except Exception:
        return None
    row.last_used_at = datetime.now(tz=timezone.utc)
    await db.commit()
    return plain
