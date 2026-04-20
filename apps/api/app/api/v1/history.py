"""History CRUD: work experience, education, skills, achievements + a unified timeline feed."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import (
    Achievement,
    Education,
    Skill,
    WorkExperience,
)
from app.models.jobs import Organization
from app.models.user import User
from app.schemas.history import (
    AchievementIn,
    AchievementOut,
    EducationIn,
    EducationOut,
    SkillIn,
    SkillOut,
    TimelineEvent,
    WorkExperienceIn,
    WorkExperienceOut,
)

router = APIRouter(prefix="/history", tags=["history"])


# ----- generic CRUD helpers ---------------------------------------------------

async def _list_for_user(db: AsyncSession, model, user_id: int):
    stmt = select(model).where(model.user_id == user_id, model.deleted_at.is_(None))
    return (await db.execute(stmt)).scalars().all()


async def _get_owned(db: AsyncSession, model, entity_id: int, user_id: int):
    stmt = select(model).where(
        model.id == entity_id, model.user_id == user_id, model.deleted_at.is_(None)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return obj


async def _attach_org_names(db: AsyncSession, items) -> None:
    """Set `organization_name` on each item for which `organization_id` is set.

    Includes soft-deleted organizations so stale references still resolve to a
    readable name until the user reassigns them. Writes the name to a transient
    attribute so the Pydantic response model picks it up via `from_attributes`.
    """
    org_ids = {getattr(i, "organization_id", None) for i in items}
    org_ids.discard(None)
    if not org_ids:
        for i in items:
            i.organization_name = None
        return
    rows = (
        await db.execute(
            select(Organization.id, Organization.name).where(Organization.id.in_(org_ids))
        )
    ).all()
    name_by_id = {row[0]: row[1] for row in rows}
    for i in items:
        i.organization_name = name_by_id.get(getattr(i, "organization_id", None))


# ----- WorkExperience ---------------------------------------------------------

@router.get("/work", response_model=list[WorkExperienceOut])
async def list_work(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkExperience]:
    items = await _list_for_user(db, WorkExperience, user.id)
    await _attach_org_names(db, items)
    return items


@router.post("/work", response_model=WorkExperienceOut, status_code=status.HTTP_201_CREATED)
async def create_work(
    payload: WorkExperienceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkExperience:
    obj = WorkExperience(user_id=user.id, **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    await _attach_org_names(db, [obj])
    return obj


@router.put("/work/{entity_id}", response_model=WorkExperienceOut)
async def update_work(
    entity_id: int,
    payload: WorkExperienceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkExperience:
    obj = await _get_owned(db, WorkExperience, entity_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    await _attach_org_names(db, [obj])
    return obj


@router.delete("/work/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    obj = await _get_owned(db, WorkExperience, entity_id, user.id)
    from datetime import datetime, timezone
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# ----- Education --------------------------------------------------------------

@router.get("/education", response_model=list[EducationOut])
async def list_education(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Education]:
    items = await _list_for_user(db, Education, user.id)
    await _attach_org_names(db, items)
    return items


@router.post("/education", response_model=EducationOut, status_code=status.HTTP_201_CREATED)
async def create_education(
    payload: EducationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Education:
    obj = Education(user_id=user.id, **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    await _attach_org_names(db, [obj])
    return obj


@router.put("/education/{entity_id}", response_model=EducationOut)
async def update_education(
    entity_id: int,
    payload: EducationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Education:
    obj = await _get_owned(db, Education, entity_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    await _attach_org_names(db, [obj])
    return obj


@router.delete("/education/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    obj = await _get_owned(db, Education, entity_id, user.id)
    from datetime import datetime, timezone
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# ----- Skill ------------------------------------------------------------------

@router.get("/skills", response_model=list[SkillOut])
async def list_skills(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Skill]:
    return await _list_for_user(db, Skill, user.id)


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Skill:
    obj = Skill(user_id=user.id, **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/skills/{entity_id}", response_model=SkillOut)
async def update_skill(
    entity_id: int,
    payload: SkillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Skill:
    obj = await _get_owned(db, Skill, entity_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/skills/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    obj = await _get_owned(db, Skill, entity_id, user.id)
    from datetime import datetime, timezone
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# ----- Achievement ------------------------------------------------------------

@router.get("/achievements", response_model=list[AchievementOut])
async def list_achievements(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Achievement]:
    return await _list_for_user(db, Achievement, user.id)


@router.post(
    "/achievements", response_model=AchievementOut, status_code=status.HTTP_201_CREATED
)
async def create_achievement(
    payload: AchievementIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Achievement:
    obj = Achievement(user_id=user.id, **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/achievements/{entity_id}", response_model=AchievementOut)
async def update_achievement(
    entity_id: int,
    payload: AchievementIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Achievement:
    obj = await _get_owned(db, Achievement, entity_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/achievements/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_achievement(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    obj = await _get_owned(db, Achievement, entity_id, user.id)
    from datetime import datetime, timezone
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# ----- Timeline ---------------------------------------------------------------

@router.get("/timeline", response_model=list[TimelineEvent])
async def timeline(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TimelineEvent]:
    """Unified feed of every dated history event for the Career Timeline page."""
    events: list[TimelineEvent] = []
    works = await _list_for_user(db, WorkExperience, user.id)
    educations = await _list_for_user(db, Education, user.id)

    # Pre-load referenced organization names so the timeline can show them as
    # subtitles without issuing N+1 queries.
    org_ids = {w.organization_id for w in works if w.organization_id} | {
        e.organization_id for e in educations if e.organization_id
    }
    org_names: dict[int, str] = {}
    if org_ids:
        rows = (
            await db.execute(
                select(Organization.id, Organization.name).where(Organization.id.in_(org_ids))
            )
        ).all()
        org_names = {row[0]: row[1] for row in rows}

    for w in works:
        events.append(
            TimelineEvent(
                kind="work",
                id=w.id,
                title=w.title,
                subtitle=org_names.get(w.organization_id) if w.organization_id else None,
                start_date=w.start_date,
                end_date=w.end_date,
                metadata={"location": w.location, "employment_type": w.employment_type},
            )
        )
    for e in educations:
        org_name = org_names.get(e.organization_id) if e.organization_id else None
        events.append(
            TimelineEvent(
                kind="education",
                id=e.id,
                title=(
                    f"{e.degree or ''} {e.field_of_study or ''}".strip()
                    or org_name
                    or "Education"
                ),
                subtitle=org_name,
                start_date=e.start_date,
                end_date=e.end_date,
                metadata={"gpa": float(e.gpa) if e.gpa is not None else None},
            )
        )
    for a in await _list_for_user(db, Achievement, user.id):
        events.append(
            TimelineEvent(
                kind="achievement",
                id=a.id,
                title=a.title,
                subtitle=a.issuer,
                start_date=a.date_awarded,
                end_date=a.date_awarded,
                metadata={"type": a.type},
            )
        )

    events.sort(
        key=lambda ev: (ev.start_date or ev.end_date or __import__("datetime").date.min),
        reverse=True,
    )
    return events
