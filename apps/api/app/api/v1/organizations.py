"""Organization CRUD + typeahead search.

Organizations are shared across users — one "MIT" entry is reusable whether the
user got a degree there, worked there, or is applying there. The UI creates
them on demand from free-form typed names (Monarch Money–style merchants).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import Contact, Education, WorkExperience
from app.models.jobs import Organization, TrackedJob
from app.models.user import User
from app.schemas.organizations import (
    ORG_TYPES,
    OrganizationIn,
    OrganizationOut,
    OrganizationSummary,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _validate_type(org_type: str) -> str:
    if org_type not in ORG_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown organization type '{org_type}'. Allowed: {sorted(ORG_TYPES)}",
        )
    return org_type


@router.get("", response_model=list[OrganizationSummary])
async def list_organizations(
    q: str | None = Query(default=None, description="Case-insensitive prefix search on name"),
    type: str | None = Query(default=None, description="Filter by type"),
    limit: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Organization]:
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q}%"))
    if type:
        stmt = stmt.where(Organization.type == type)
    stmt = stmt.order_by(Organization.name).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{org_id}", response_model=OrganizationOut)
async def get_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return obj


@router.get("/{org_id}/usage")
async def organization_usage(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Counts of how this organization is referenced, scoped to the current user."""

    async def count(stmt) -> int:
        return int((await db.execute(stmt)).scalar() or 0)

    return {
        "work_experiences": await count(
            select(func.count())
            .select_from(WorkExperience)
            .where(
                WorkExperience.user_id == user.id,
                WorkExperience.organization_id == org_id,
                WorkExperience.deleted_at.is_(None),
            )
        ),
        "educations": await count(
            select(func.count())
            .select_from(Education)
            .where(
                Education.user_id == user.id,
                Education.organization_id == org_id,
                Education.deleted_at.is_(None),
            )
        ),
        "tracked_jobs": await count(
            select(func.count())
            .select_from(TrackedJob)
            .where(
                TrackedJob.user_id == user.id,
                TrackedJob.organization_id == org_id,
                TrackedJob.deleted_at.is_(None),
            )
        ),
        "contacts": await count(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.user_id == user.id,
                Contact.organization_id == org_id,
                Contact.deleted_at.is_(None),
            )
        ),
    }


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    _validate_type(payload.type)
    # Case-insensitive exact-name match on a non-deleted org → return it
    # instead of creating a duplicate. Keeps the combobox "create on Enter"
    # flow idempotent when the user types something that already exists.
    existing_stmt = select(Organization).where(
        func.lower(Organization.name) == payload.name.strip().lower(),
        Organization.deleted_at.is_(None),
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return existing

    obj = Organization(**payload.model_dump(exclude_unset=True))
    obj.name = obj.name.strip()
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{org_id}", response_model=OrganizationOut)
async def update_organization(
    org_id: int,
    payload: OrganizationIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Organization:
    _validate_type(payload.type)
    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    from datetime import datetime, timezone

    stmt = select(Organization).where(
        Organization.id == org_id, Organization.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()
