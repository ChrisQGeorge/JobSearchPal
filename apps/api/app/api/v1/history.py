"""History CRUD: work experience, education, skills, achievements + a unified timeline feed."""

# NOTE: intentionally NOT importing `from __future__ import annotations` — the
# `_simple_crud` factory relies on FastAPI's runtime introspection of parameter
# annotations to determine which params are request bodies. With stringified
# annotations, FastAPI's `get_type_hints` can't resolve `pydantic_in` as it's
# a closure variable, so it falls back to "query param" for the body.

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import (
    Achievement,
    Certification,
    Contact,
    Course,
    CourseSkill,
    CustomEvent,
    Education,
    Language,
    Presentation,
    Project,
    ProjectSkill,
    Publication,
    Skill,
    VolunteerWork,
    WorkExperience,
    WorkExperienceSkill,
)
from app.models.links import EntityLink
from app.models.jobs import Organization
from app.models.user import User
from app.schemas.history import (
    AchievementIn,
    AchievementOut,
    CertificationIn,
    CertificationOut,
    ContactIn,
    ContactOut,
    CourseIn,
    CourseOut,
    CustomEventIn,
    CustomEventOut,
    EducationIn,
    EducationOut,
    EntityLinkIn,
    EntityLinkOut,
    LanguageIn,
    LanguageOut,
    LinkedSkill,
    LinkSkillIn,
    PresentationIn,
    PresentationOut,
    ProjectIn,
    ProjectOut,
    PublicationIn,
    PublicationOut,
    SkillIn,
    SkillOut,
    TimelineEvent,
    VolunteerWorkIn,
    VolunteerWorkOut,
    WorkExperienceIn,
    WorkExperienceOut,
)

router = APIRouter(prefix="/history", tags=["history"])


# ----- generic CRUD helpers ---------------------------------------------------

async def _list_for_user(db: AsyncSession, model, user_id: int):
    """Return all rows for a user, sorted with most-recent end_date first.

    Null `end_date` means "current" so those rows sort to the top. Rows
    sharing a rank fall back to alphabetical on their primary label
    (title / name / degree — whichever the model has).
    """
    stmt = select(model).where(model.user_id == user_id, model.deleted_at.is_(None))
    rows = list((await db.execute(stmt)).scalars().all())

    # Figure out a label attr for alphabetical tiebreak.
    label_attr: Optional[str] = None
    for candidate in ("title", "name", "degree", "field_of_study"):
        if hasattr(model, candidate):
            label_attr = candidate
            break

    has_end = hasattr(model, "end_date")

    def sort_key(r):
        # Tuple: (0 if current/no-end else 1, negated timestamp so newer first,
        # lowercased label for alpha tiebreak).
        end = getattr(r, "end_date", None) if has_end else None
        if end is None:
            bucket = 0
            sortable = 0
        else:
            bucket = 1
            # Convert to ordinal so we can negate.
            try:
                sortable = -end.toordinal()
            except Exception:
                sortable = 0
        label = ""
        if label_attr:
            v = getattr(r, label_attr, None)
            label = str(v).lower() if v else ""
        return (bucket, sortable, label)

    rows.sort(key=sort_key)
    return rows


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
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# ----- Skill ------------------------------------------------------------------

@router.get("/skills", response_model=list[SkillOut])
async def list_skills(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SkillOut]:
    rows = await _list_for_user(db, Skill, user.id)
    if not rows:
        return []
    ids = [r.id for r in rows]

    # Count attachments from all four sources.
    from app.models.history import (
        WorkExperienceSkill as _WES,
        CourseSkill as _CS,
        ProjectSkill as _PS,
        WorkExperience as _WE,
        Project as _P,
    )
    from app.models.links import EntityLink as _EL

    wes_counts = dict(
        (await db.execute(
            select(_WES.skill_id, func.count()).where(_WES.skill_id.in_(ids)).group_by(_WES.skill_id)
        )).all()
    )
    cs_counts = dict(
        (await db.execute(
            select(_CS.skill_id, func.count()).where(_CS.skill_id.in_(ids)).group_by(_CS.skill_id)
        )).all()
    )
    ps_counts = dict(
        (await db.execute(
            select(_PS.skill_id, func.count()).where(_PS.skill_id.in_(ids)).group_by(_PS.skill_id)
        )).all()
    )
    # EntityLink: skill can be on either end. Count anything pointing to a skill.
    el_to_counts = dict(
        (await db.execute(
            select(_EL.to_entity_id, func.count()).where(
                _EL.user_id == user.id,
                _EL.to_entity_type == "skill",
                _EL.to_entity_id.in_(ids),
            ).group_by(_EL.to_entity_id)
        )).all()
    )
    el_from_counts = dict(
        (await db.execute(
            select(_EL.from_entity_id, func.count()).where(
                _EL.user_id == user.id,
                _EL.from_entity_type == "skill",
                _EL.from_entity_id.in_(ids),
            ).group_by(_EL.from_entity_id)
        )).all()
    )

    # Work-history years = sum of (end_date - start_date) for every
    # WorkExperience linked via work_experience_skills, rounded UP to
    # the nearest whole year. Ongoing roles (end_date IS NULL) use
    # today's date. One query pulls the (skill_id, start, end) triples
    # so we aggregate in Python.
    import datetime as _dt
    import math as _math

    work_range_rows = (
        await db.execute(
            select(_WES.skill_id, _WE.start_date, _WE.end_date)
            .join(_WE, _WES.work_experience_id == _WE.id)
            .where(
                _WES.skill_id.in_(ids),
                _WE.user_id == user.id,
                _WE.deleted_at.is_(None),
            )
        )
    ).all()
    # Projects opted in via `include_as_work_history` add to the same total.
    # For ongoing projects (is_ongoing=True with no end_date), we use today.
    project_range_rows = (
        await db.execute(
            select(
                _PS.skill_id,
                _P.start_date,
                _P.end_date,
                _P.is_ongoing,
            )
            .join(_P, _PS.project_id == _P.id)
            .where(
                _PS.skill_id.in_(ids),
                _P.user_id == user.id,
                _P.deleted_at.is_(None),
                _P.include_as_work_history.is_(True),
            )
        )
    ).all()
    today = _dt.date.today()
    days_by_skill: dict[int, int] = {}
    for skill_id, start_date, end_date in work_range_rows:
        if start_date is None:
            continue
        end = end_date or today
        delta = (end - start_date).days
        if delta <= 0:
            continue
        days_by_skill[skill_id] = days_by_skill.get(skill_id, 0) + delta
    for skill_id, start_date, end_date, is_ongoing in project_range_rows:
        if start_date is None:
            continue
        end = end_date or (today if is_ongoing else None)
        if end is None:
            continue
        delta = (end - start_date).days
        if delta <= 0:
            continue
        days_by_skill[skill_id] = days_by_skill.get(skill_id, 0) + delta

    out: list[SkillOut] = []
    for r in rows:
        count = (
            wes_counts.get(r.id, 0)
            + cs_counts.get(r.id, 0)
            + ps_counts.get(r.id, 0)
            + el_to_counts.get(r.id, 0)
            + el_from_counts.get(r.id, 0)
        )
        row = SkillOut.model_validate(r)
        row.attachment_count = int(count)
        total_days = days_by_skill.get(r.id)
        row.work_history_years = (
            int(_math.ceil(total_days / 365.25)) if total_days else None
        )
        out.append(row)
    return out


class MissingSkillOut(BaseModel):
    """One entry per distinct skill-name mentioned across the user's tracked
    jobs' required/nice-to-have lists that is NOT already in their catalog
    (neither as a Skill.name nor as one of its aliases). Case-insensitive
    match."""

    name: str
    job_count: int
    tier_counts: dict[str, int]  # {"required": N, "nice_to_have": M}
    job_ids: list[int]  # small sample (first 10) for UI linking


@router.get("/skills/missing-from-jobs", response_model=list[MissingSkillOut])
async def skills_missing_from_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MissingSkillOut]:
    """Scan every TrackedJob's `required_skills` + `nice_to_have_skills` and
    return skill names that DON'T appear in the user's Skills catalog (by
    name or alias). Sorted by job count descending so the user can tell
    which skills are in highest demand relative to their resume.

    Client renders this as a collapsible "missing from tracked jobs"
    section at the top of the Skills catalog page."""
    from app.models.jobs import TrackedJob as _TJ

    # Build the set of known catalog identifiers (lowercased).
    skills = (
        await db.execute(
            select(Skill).where(
                Skill.user_id == user.id,
                Skill.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    known: set[str] = set()
    for s in skills:
        known.add(s.name.lower().strip())
        for a in s.aliases or []:
            if a and a.strip():
                known.add(str(a).lower().strip())

    # Pull tracked jobs' JD skill lists.
    tj_rows = (
        await db.execute(
            select(
                _TJ.id,
                _TJ.required_skills,
                _TJ.nice_to_have_skills,
            ).where(
                _TJ.user_id == user.id,
                _TJ.deleted_at.is_(None),
            )
        )
    ).all()

    # Aggregate. Key is the lowercased name so "React" and "react" collapse;
    # we keep the most common-cased version as the display name.
    class _Agg:
        __slots__ = ("display", "job_ids", "req", "nice", "case_votes")

        def __init__(self, display: str) -> None:
            self.display = display
            self.job_ids: list[int] = []
            self.req = 0
            self.nice = 0
            self.case_votes: dict[str, int] = {display: 1}

    agg: dict[str, _Agg] = {}
    for job_id, req_list, nice_list in tj_rows:
        req_set = {
            str(x).strip()
            for x in (req_list or [])
            if x and str(x).strip()
        }
        nice_set = {
            str(x).strip()
            for x in (nice_list or [])
            if x and str(x).strip()
        }
        for raw in req_set | nice_set:
            key = raw.lower()
            if key in known:
                continue
            entry = agg.get(key)
            if entry is None:
                entry = _Agg(raw)
                agg[key] = entry
            else:
                entry.case_votes[raw] = entry.case_votes.get(raw, 0) + 1
                # Pick the best-voted display casing.
                entry.display = max(
                    entry.case_votes.items(), key=lambda kv: (kv[1], kv[0])
                )[0]
            if job_id not in entry.job_ids:
                entry.job_ids.append(job_id)
            if raw in req_set:
                entry.req += 1
            if raw in nice_set:
                entry.nice += 1

    out = [
        MissingSkillOut(
            name=e.display,
            job_count=len(e.job_ids),
            tier_counts={"required": e.req, "nice_to_have": e.nice},
            job_ids=e.job_ids[:10],
        )
        for e in agg.values()
    ]
    out.sort(key=lambda m: (-m.job_count, m.name.lower()))
    return out


class BulkUpdateSkillsIn(BaseModel):
    """Apply the same field values to every skill in `ids`. Any field left
    unset is ignored (the row's existing value stays). To explicitly clear
    a field (set to NULL) include it in `clear_fields`."""

    ids: list[int] = Field(min_length=1)
    category: Optional[str] = None
    proficiency: Optional[str] = None
    years_experience: Optional[float] = None
    last_used_date: Optional[date] = None
    evidence_notes: Optional[str] = None
    clear_fields: list[str] = Field(default_factory=list)


@router.post("/skills/bulk-update", response_model=dict)
async def bulk_update_skills(
    payload: BulkUpdateSkillsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Apply the same field values to multiple catalog skills at once.
    Used by the Skills panel's bulk-edit action when the user has selected
    several rows and wants to stamp them all with e.g. proficiency=expert."""
    _ALLOWED_CLEAR = {
        "category", "proficiency", "years_experience",
        "last_used_date", "evidence_notes",
    }

    rows = (
        await db.execute(
            select(Skill).where(
                Skill.user_id == user.id,
                Skill.id.in_(payload.ids),
                Skill.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if not rows:
        return {"updated": 0, "skipped": len(payload.ids)}

    # Only write fields the caller explicitly set (exclude_unset).
    explicit_updates = payload.model_dump(
        exclude_unset=True, exclude={"ids", "clear_fields"}
    )
    clears = {f for f in payload.clear_fields if f in _ALLOWED_CLEAR}

    for s in rows:
        for field, value in explicit_updates.items():
            if field in clears:
                # Clear takes precedence if the field is in both lists.
                continue
            setattr(s, field, value)
        for field in clears:
            setattr(s, field, None)

    await db.commit()
    return {
        "updated": len(rows),
        "skipped": len(payload.ids) - len(rows),
    }


@router.get("/skills/{skill_id:int}/attachments")
async def skill_attachments(
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List every entity this skill is attached to, with enough context
    (org names, date ranges, usage notes, relation labels) to render a
    rich "where is this skill used?" panel on the Skills Catalog page."""
    from app.models.history import (
        Course as _Course,
        Education as _Education,
        Project as _Project,
        ProjectSkill as _PS,
        WorkExperience as _WE,
        WorkExperienceSkill as _WES,
        CourseSkill as _CS,
    )
    from app.models.links import EntityLink as _EL
    from app.models.jobs import Organization as _Org

    # Verify ownership.
    await _get_owned(db, Skill, skill_id, user.id)

    # --- Work experiences (with org name, date range, usage notes) --------
    work_rows = list(
        (
            await db.execute(
                select(
                    _WE.id,
                    _WE.title,
                    _WE.organization_id,
                    _WE.start_date,
                    _WE.end_date,
                    _WES.usage_notes,
                ).join(_WES, _WES.work_experience_id == _WE.id)
                .where(_WES.skill_id == skill_id, _WE.user_id == user.id)
                # MySQL-portable "nulls first on desc": explicit IS NULL
                # sort key first — `col IS NULL` evaluates to 1 for null
                # (sorts before 0 descending), then within each group by
                # the actual date descending. Rows with no end_date (still
                # ongoing) sit at the top.
                .order_by(
                    _WE.end_date.is_(None).desc(),
                    _WE.end_date.desc(),
                )
            )
        ).all()
    )

    # --- Courses (with parent education's org name + course dates) --------
    course_rows = list(
        (
            await db.execute(
                select(
                    _Course.id,
                    _Course.code,
                    _Course.name,
                    _Course.term,
                    _Course.start_date,
                    _Course.end_date,
                    _Education.id,
                    _Education.organization_id,
                    _Education.degree,
                    _CS.usage_notes,
                ).join(_CS, _CS.course_id == _Course.id)
                .join(_Education, _Education.id == _Course.education_id)
                .where(_CS.skill_id == skill_id, _Education.user_id == user.id)
                .order_by(
                    _Course.end_date.is_(None).desc(),
                    _Course.end_date.desc(),
                )
            )
        ).all()
    )

    # --- Resolve org names in one shot -----------------------------------
    org_ids = {r[2] for r in work_rows if r[2]} | {r[7] for r in course_rows if r[7]}
    org_names: dict[int, str] = {}
    if org_ids:
        rows = (
            await db.execute(
                select(_Org.id, _Org.name).where(_Org.id.in_(org_ids))
            )
        ).all()
        org_names = {row[0]: row[1] for row in rows}

    # --- Projects (via the dedicated project_skills junction) ------------
    project_rows = list(
        (
            await db.execute(
                select(
                    _Project.id,
                    _Project.name,
                    _Project.role,
                    _Project.start_date,
                    _Project.end_date,
                    _Project.is_ongoing,
                    _PS.usage_notes,
                ).join(_PS, _PS.project_id == _Project.id)
                .where(_PS.skill_id == skill_id, _Project.user_id == user.id)
                .order_by(
                    _Project.end_date.is_(None).desc(),
                    _Project.end_date.desc(),
                )
            )
        ).all()
    )

    # --- Polymorphic entity links ----------------------------------------
    link_rows = list(
        (
            await db.execute(
                select(_EL).where(
                    _EL.user_id == user.id,
                    ((_EL.from_entity_type == "skill") & (_EL.from_entity_id == skill_id))
                    | ((_EL.to_entity_type == "skill") & (_EL.to_entity_id == skill_id)),
                )
            )
        ).scalars().all()
    )
    other_links: list[dict] = []
    for l in link_rows:
        if l.to_entity_id == skill_id and l.to_entity_type == "skill":
            other_type = l.from_entity_type
            other_id = l.from_entity_id
        else:
            other_type = l.to_entity_type
            other_id = l.to_entity_id
        label = None
        try:
            label = await _label_for(db, other_type, other_id)
        except Exception:
            pass
        other_links.append(
            {
                "link_id": l.id,
                "other_type": other_type,
                "other_id": other_id,
                "other_label": label or f"{other_type} #{other_id}",
                "relation": l.relation,
                "note": l.note,
            }
        )

    def _iso(d):
        return d.isoformat() if d else None

    return {
        "work_experiences": [
            {
                "id": r[0],
                "title": r[1],
                "organization_id": r[2],
                "organization_name": org_names.get(r[2]) if r[2] else None,
                "start_date": _iso(r[3]),
                "end_date": _iso(r[4]),
                "usage_notes": r[5],
            }
            for r in work_rows
        ],
        "courses": [
            {
                "id": r[0],
                "code": r[1],
                "name": r[2],
                "term": r[3],
                "start_date": _iso(r[4]),
                "end_date": _iso(r[5]),
                "education_id": r[6],
                "education_degree": r[8],
                "organization_id": r[7],
                "organization_name": org_names.get(r[7]) if r[7] else None,
                "usage_notes": r[9],
            }
            for r in course_rows
        ],
        "projects": [
            {
                "id": r[0],
                "name": r[1],
                "role": r[2],
                "start_date": _iso(r[3]),
                "end_date": _iso(r[4]),
                "is_ongoing": bool(r[5]),
                "usage_notes": r[6],
            }
            for r in project_rows
        ],
        "other_links": other_links,
    }


class SkillMergeIn(BaseModel):
    keep_id: int
    merge_ids: list[int]


@router.post("/skills/merge", response_model=SkillOut)
async def merge_skills(
    payload: SkillMergeIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Skill:
    """Merge one or more skills into a single canonical row.

    Every reference in `work_experience_skills`, `course_skills`, and
    polymorphic `entity_links` pointing at a merged skill gets re-pointed
    at `keep_id`. The merged skills' names (and any of their existing
    aliases) are appended to the keeper's `aliases` list, then the merged
    rows are soft-deleted. Idempotent against re-merge — unique-constraint
    collisions on the junction tables are collapsed automatically.
    """
    from datetime import datetime as _dt, timezone as _tz

    from app.models.history import (
        CourseSkill as _CS,
        WorkExperienceSkill as _WES,
    )
    from app.models.links import EntityLink as _EL

    if not payload.merge_ids:
        raise HTTPException(status_code=422, detail="merge_ids is required")
    if payload.keep_id in payload.merge_ids:
        raise HTTPException(
            status_code=422, detail="keep_id must not also appear in merge_ids"
        )

    keeper = await _get_owned(db, Skill, payload.keep_id, user.id)
    losers: list[Skill] = []
    for mid in payload.merge_ids:
        losers.append(await _get_owned(db, Skill, mid, user.id))

    def _lower(s: str | None) -> str:
        return (s or "").lower()

    aliases = list(keeper.aliases or [])
    alias_set = {_lower(a) for a in aliases if isinstance(a, str)}
    alias_set.add(_lower(keeper.name))  # don't re-add the canonical name

    for loser in losers:
        if loser.name and _lower(loser.name) not in alias_set:
            aliases.append(loser.name)
            alias_set.add(_lower(loser.name))
        for a in loser.aliases or []:
            if isinstance(a, str) and _lower(a) not in alias_set:
                aliases.append(a)
                alias_set.add(_lower(a))

    keeper.aliases = aliases or None

    loser_ids = [l.id for l in losers]

    # Re-point WorkExperienceSkill rows. The unique constraint on
    # (work_experience_id, skill_id) means some targets may already have the
    # keeper linked; delete the would-be-duplicate rows first, then update.
    existing_wes_work_ids = {
        r[0]
        for r in (
            await db.execute(
                select(_WES.work_experience_id).where(
                    _WES.skill_id == keeper.id
                )
            )
        ).all()
    }
    for row in (
        await db.execute(
            select(_WES).where(_WES.skill_id.in_(loser_ids))
        )
    ).scalars().all():
        if row.work_experience_id in existing_wes_work_ids:
            await db.delete(row)
        else:
            row.skill_id = keeper.id
            existing_wes_work_ids.add(row.work_experience_id)

    # Same treatment for CourseSkill.
    existing_cs_course_ids = {
        r[0]
        for r in (
            await db.execute(
                select(_CS.course_id).where(_CS.skill_id == keeper.id)
            )
        ).all()
    }
    for row in (
        await db.execute(select(_CS).where(_CS.skill_id.in_(loser_ids)))
    ).scalars().all():
        if row.course_id in existing_cs_course_ids:
            await db.delete(row)
        else:
            row.skill_id = keeper.id
            existing_cs_course_ids.add(row.course_id)

    # Re-point polymorphic EntityLinks on either end.
    for row in (
        await db.execute(
            select(_EL).where(
                _EL.user_id == user.id,
                (
                    (_EL.to_entity_type == "skill") & (_EL.to_entity_id.in_(loser_ids))
                )
                | (
                    (_EL.from_entity_type == "skill")
                    & (_EL.from_entity_id.in_(loser_ids))
                ),
            )
        )
    ).scalars().all():
        if row.to_entity_type == "skill" and row.to_entity_id in loser_ids:
            row.to_entity_id = keeper.id
        if row.from_entity_type == "skill" and row.from_entity_id in loser_ids:
            row.from_entity_id = keeper.id

    # Soft-delete the merged skills.
    now = _dt.now(tz=_tz.utc)
    for loser in losers:
        loser.deleted_at = now

    await db.commit()
    await db.refresh(keeper)
    return keeper


@router.post("/skills", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(
    payload: SkillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Skill:
    """Create a skill, case-insensitively deduplicated per-user.

    If a skill with the same name (case-insensitive) already exists for this
    user, return the existing row instead of creating a new one. Preserves
    the original capitalization the user typed first.
    """
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    lname = name.lower()
    # Check both primary name AND aliases for an existing match.
    all_rows = (
        await db.execute(
            select(Skill).where(
                Skill.user_id == user.id,
                Skill.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    for r in all_rows:
        if (r.name or "").lower() == lname:
            return r
        for alias in (r.aliases or []):
            if isinstance(alias, str) and alias.lower() == lname:
                return r
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
    obj.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# ----- Generic CRUD for the remaining single-user entities -------------------
# Each entity has the same 4 verbs (list / create / update / soft-delete). The
# factory keeps this file compact. Courses and Contacts get specialization
# below.


def _soft_delete(obj) -> None:
    obj.deleted_at = datetime.now(tz=timezone.utc)


# For a subset of models, a legacy free-text column is kept alongside the
# new `organization_id` FK (migration 0013). When the user picks an org via
# the combobox, we mirror the org's name into that free-text column so
# reads still work without every caller joining through Organization.
_MIRROR_ORG_NAME_TO: dict[type, str] = {
    Certification: "issuer",
    Achievement: "issuer",
    Publication: "venue",
    VolunteerWork: "organization",
}


async def _mirror_org_name_if_needed(
    db: AsyncSession, obj
) -> None:
    """If `obj.organization_id` is set, overwrite the legacy name-field with
    the resolved Organization.name. If the name-field is a NOT NULL column
    (VolunteerWork.organization) and both FK + free-text are missing, raise
    a 422 rather than letting the DB commit explode on the constraint."""
    attr = _MIRROR_ORG_NAME_TO.get(type(obj))
    if not attr:
        return
    org_id = getattr(obj, "organization_id", None)
    current = getattr(obj, attr, None)
    if org_id is not None:
        row = (
            await db.execute(
                select(Organization.name).where(Organization.id == org_id)
            )
        ).first()
        if row and row[0]:
            setattr(obj, attr, row[0])
            return
        # FK was set but org doesn't exist / was soft-deleted. Fall through
        # to the required-text check below.
    # Volunteer's `organization` column is NOT NULL; other tables allow null.
    if attr == "organization" and not (current and str(current).strip()):
        raise HTTPException(
            status_code=422,
            detail="Provide an Organization (pick from the combobox) or type a name.",
        )


def _simple_crud(path: str, model, pydantic_in, pydantic_out) -> None:
    """Register list/create/update/delete routes for a user-owned model."""

    @router.get(f"/{path}", response_model=list[pydantic_out], name=f"list_{path}")
    async def _list(
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        return await _list_for_user(db, model, user.id)

    @router.post(
        f"/{path}",
        response_model=pydantic_out,
        status_code=status.HTTP_201_CREATED,
        name=f"create_{path}",
    )
    async def _create(
        payload: pydantic_in,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        obj = model(user_id=user.id, **payload.model_dump(exclude_unset=True))
        await _mirror_org_name_if_needed(db, obj)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @router.put(
        f"/{path}/{{entity_id}}",
        response_model=pydantic_out,
        name=f"update_{path}",
    )
    async def _update(
        entity_id: int,
        payload: pydantic_in,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        obj = await _get_owned(db, model, entity_id, user.id)
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(obj, k, v)
        await _mirror_org_name_if_needed(db, obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @router.delete(
        f"/{path}/{{entity_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{path}",
    )
    async def _delete(
        entity_id: int,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        obj = await _get_owned(db, model, entity_id, user.id)
        _soft_delete(obj)
        await db.commit()


_simple_crud("certifications", Certification, CertificationIn, CertificationOut)
_simple_crud("languages", Language, LanguageIn, LanguageOut)
_simple_crud("projects", Project, ProjectIn, ProjectOut)
_simple_crud("publications", Publication, PublicationIn, PublicationOut)
_simple_crud("presentations", Presentation, PresentationIn, PresentationOut)
_simple_crud("volunteer", VolunteerWork, VolunteerWorkIn, VolunteerWorkOut)
_simple_crud("custom-events", CustomEvent, CustomEventIn, CustomEventOut)


# ----- Courses (nested under an Education entry) -----------------------------


async def _get_owned_education(
    db: AsyncSession, education_id: int, user_id: int
) -> Education:
    stmt = select(Education).where(
        Education.id == education_id,
        Education.user_id == user_id,
        Education.deleted_at.is_(None),
    )
    ed = (await db.execute(stmt)).scalar_one_or_none()
    if ed is None:
        raise HTTPException(status_code=404, detail="Education entry not found")
    return ed


async def _get_owned_course(
    db: AsyncSession, course_id: int, user_id: int
) -> Course:
    stmt = (
        select(Course)
        .join(Education, Course.education_id == Education.id)
        .where(
            Course.id == course_id,
            Course.deleted_at.is_(None),
            Education.user_id == user_id,
            Education.deleted_at.is_(None),
        )
    )
    c = (await db.execute(stmt)).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return c


@router.get("/courses", response_model=list[CourseOut])
async def list_courses(
    education_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Course]:
    """All courses for this user, optionally filtered to a single education entry."""
    stmt = (
        select(Course)
        .join(Education, Course.education_id == Education.id)
        .where(
            Education.user_id == user.id,
            Education.deleted_at.is_(None),
            Course.deleted_at.is_(None),
        )
    )
    if education_id is not None:
        stmt = stmt.where(Course.education_id == education_id)
    stmt = stmt.order_by(Course.term.asc(), Course.id.asc())
    return list((await db.execute(stmt)).scalars().all())


@router.post("/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
async def create_course(
    payload: CourseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Course:
    await _get_owned_education(db, payload.education_id, user.id)
    obj = Course(**payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/courses/{entity_id}", response_model=CourseOut)
async def update_course(
    entity_id: int,
    payload: CourseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Course:
    obj = await _get_owned_course(db, entity_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    if "education_id" in data and data["education_id"] != obj.education_id:
        await _get_owned_education(db, data["education_id"], user.id)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/courses/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    obj = await _get_owned_course(db, entity_id, user.id)
    _soft_delete(obj)
    await db.commit()


# ----- Contacts (user-owned, optional organization link) ---------------------


@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Contact]:
    items = await _list_for_user(db, Contact, user.id)
    await _attach_org_names(db, items)
    return items


@router.post(
    "/contacts",
    response_model=ContactOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    payload: ContactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Contact:
    obj = Contact(user_id=user.id, **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    await _attach_org_names(db, [obj])
    return obj


@router.put("/contacts/{entity_id}", response_model=ContactOut)
async def update_contact(
    entity_id: int,
    payload: ContactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Contact:
    obj = await _get_owned(db, Contact, entity_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    await db.commit()
    await db.refresh(obj)
    await _attach_org_names(db, [obj])
    return obj


@router.delete("/contacts/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    obj = await _get_owned(db, Contact, entity_id, user.id)
    _soft_delete(obj)
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
        gaps: list[str] = []
        if not w.start_date:
            gaps.append("no start date")
        if not w.end_date and not (w.reason_for_leaving or "").lower().startswith(
            ("current", "ongoing", "present")
        ):
            # No end_date AND no signal that the role is ongoing → probably stale.
            # (Work doesn't have an is_ongoing flag — we infer from end_date absence.)
            pass  # intentional: absence of end_date is the ongoing signal
        # "no highlights" alone is too noisy — summary is the anchor signal.
        if not w.summary:
            gaps.append("no summary")
        events.append(
            TimelineEvent(
                kind="work",
                id=w.id,
                title=w.title,
                subtitle=org_names.get(w.organization_id) if w.organization_id else None,
                start_date=w.start_date,
                end_date=w.end_date,
                metadata={
                    "location": w.location,
                    "employment_type": w.employment_type,
                    "gaps": gaps,
                },
            )
        )
    for e in educations:
        org_name = org_names.get(e.organization_id) if e.organization_id else None
        e_gaps: list[str] = []
        if not e.start_date:
            e_gaps.append("no start date")
        if not e.degree and not e.field_of_study:
            e_gaps.append("no degree")
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
                metadata={
                    "gpa": float(e.gpa) if e.gpa is not None else None,
                    "gaps": e_gaps,
                },
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

    for c in await _list_for_user(db, Certification, user.id):
        events.append(
            TimelineEvent(
                kind="certification",
                id=c.id,
                title=c.name,
                subtitle=c.issuer,
                start_date=c.issued_date,
                end_date=c.expires_date or c.issued_date,
                metadata={"credential_id": c.credential_id},
            )
        )

    # Resolve project → linked work/education → org, so By Org grouping can
    # place a project under the same company or school it's associated with
    # via entity_links rather than dumping it in "Unaffiliated".
    all_projects = await _list_for_user(db, Project, user.id)
    project_effective_org: dict[int, str] = {}
    if all_projects:
        project_ids = [p.id for p in all_projects]
        links_out = list(
            (
                await db.execute(
                    select(EntityLink).where(
                        EntityLink.user_id == user.id,
                        EntityLink.from_entity_type == "project",
                        EntityLink.from_entity_id.in_(project_ids),
                        EntityLink.to_entity_type.in_(["work", "education"]),
                    )
                )
            ).scalars().all()
        )
        links_in = list(
            (
                await db.execute(
                    select(EntityLink).where(
                        EntityLink.user_id == user.id,
                        EntityLink.to_entity_type == "project",
                        EntityLink.to_entity_id.in_(project_ids),
                        EntityLink.from_entity_type.in_(["work", "education"]),
                    )
                )
            ).scalars().all()
        )
        # Build project_id → (target_type, target_id) map (first link wins).
        refs: dict[int, tuple[str, int]] = {}
        for l in links_out:
            refs.setdefault(l.from_entity_id, (l.to_entity_type, l.to_entity_id))
        for l in links_in:
            refs.setdefault(l.to_entity_id, (l.from_entity_type, l.from_entity_id))
        # Resolve the org for each referenced work/education in one pass.
        work_ids = [v[1] for v in refs.values() if v[0] == "work"]
        edu_ids = [v[1] for v in refs.values() if v[0] == "education"]
        work_org: dict[int, Optional[int]] = {}
        if work_ids:
            work_org = {
                r[0]: r[1]
                for r in (
                    await db.execute(
                        select(WorkExperience.id, WorkExperience.organization_id).where(
                            WorkExperience.id.in_(work_ids)
                        )
                    )
                ).all()
            }
        edu_org: dict[int, Optional[int]] = {}
        if edu_ids:
            edu_org = {
                r[0]: r[1]
                for r in (
                    await db.execute(
                        select(Education.id, Education.organization_id).where(
                            Education.id.in_(edu_ids)
                        )
                    )
                ).all()
            }
        for pid, (t, tid) in refs.items():
            org_id = work_org.get(tid) if t == "work" else edu_org.get(tid)
            if org_id and org_id in org_names:
                project_effective_org[pid] = org_names[org_id]

    for p in all_projects:
        p_gaps: list[str] = []
        if not p.summary and not p.description_md:
            p_gaps.append("no summary")
        events.append(
            TimelineEvent(
                kind="project",
                id=p.id,
                title=p.name,
                subtitle=p.role,
                start_date=p.start_date,
                end_date=None if p.is_ongoing else p.end_date,
                metadata={
                    "is_ongoing": p.is_ongoing,
                    "visibility": p.visibility,
                    "gaps": p_gaps,
                    # Used by the frontend when grouping By Org. Frontend falls
                    # back to subtitle when this isn't present.
                    "effective_org": project_effective_org.get(p.id),
                },
            )
        )

    for pub in await _list_for_user(db, Publication, user.id):
        events.append(
            TimelineEvent(
                kind="publication",
                id=pub.id,
                title=pub.title,
                subtitle=pub.venue,
                start_date=pub.publication_date,
                end_date=pub.publication_date,
                metadata={"type": pub.type, "doi": pub.doi},
            )
        )

    for pres in await _list_for_user(db, Presentation, user.id):
        events.append(
            TimelineEvent(
                kind="presentation",
                id=pres.id,
                title=pres.title,
                subtitle=pres.venue or pres.event_name,
                start_date=pres.date_presented,
                end_date=pres.date_presented,
                metadata={"format": pres.format, "audience_size": pres.audience_size},
            )
        )

    for v in await _list_for_user(db, VolunteerWork, user.id):
        events.append(
            TimelineEvent(
                kind="volunteer",
                id=v.id,
                title=v.role or "Volunteer",
                subtitle=v.organization,
                start_date=v.start_date,
                end_date=v.end_date,
                metadata={"cause_area": v.cause_area, "hours_total": v.hours_total},
            )
        )

    # Courses: joined via Education for ownership, pulled separately to avoid
    # re-reading the Education list.
    course_rows = (
        await db.execute(
            select(Course)
            .join(Education, Course.education_id == Education.id)
            .where(
                Education.user_id == user.id,
                Education.deleted_at.is_(None),
                Course.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    # Prefer the course's own start_date/end_date (added in migration 0008).
    # Fall back to the parent Education's range only if neither is set, so a
    # course without explicit dates still renders somewhere sensible.
    ed_dates = {
        e.id: (e.start_date, e.end_date) for e in educations
    }
    # Parent Education's organization name is the right bucket for the
    # timeline's "By org" grouping — the course's own `subtitle` is the term
    # or instructor, which would otherwise produce per-term rows.
    ed_org_id = {e.id: e.organization_id for e in educations}
    for c in course_rows:
        parent_start, parent_end = ed_dates.get(c.education_id, (None, None))
        start = c.start_date or parent_start
        end = c.end_date or parent_end
        parent_org_id = ed_org_id.get(c.education_id)
        effective_org = (
            org_names.get(parent_org_id) if parent_org_id is not None else None
        )
        events.append(
            TimelineEvent(
                kind="course",
                id=c.id,
                title=f"{c.code + ' · ' if c.code else ''}{c.name}",
                subtitle=c.term or (c.instructor or None),
                start_date=start,
                end_date=end,
                metadata={
                    "credits": float(c.credits) if c.credits is not None else None,
                    "grade": c.grade,
                    "effective_org": effective_org,
                },
            )
        )

    for ev in await _list_for_user(db, CustomEvent, user.id):
        events.append(
            TimelineEvent(
                kind="custom",
                id=ev.id,
                title=ev.title,
                subtitle=ev.type_label,
                start_date=ev.start_date,
                end_date=ev.end_date,
                metadata=ev.event_metadata,
            )
        )

    events.sort(
        key=lambda ev: (ev.start_date or ev.end_date or __import__("datetime").date.min),
        reverse=True,
    )
    return events


# ============================================================================
# Skill linking — specific Work<->Skill and Course<->Skill with usage_notes.
# ============================================================================


async def _skill_exists_for_user(
    db: AsyncSession, skill_id: int, user_id: int
) -> Skill:
    stmt = select(Skill).where(
        Skill.id == skill_id,
        Skill.user_id == user_id,
        Skill.deleted_at.is_(None),
    )
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return s


@router.get("/work/{entity_id}/skills", response_model=list[LinkedSkill])
async def list_work_skills(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LinkedSkill]:
    await _get_owned(db, WorkExperience, entity_id, user.id)
    rows = (
        await db.execute(
            select(WorkExperienceSkill, Skill)
            .join(Skill, WorkExperienceSkill.skill_id == Skill.id)
            .where(
                WorkExperienceSkill.work_experience_id == entity_id,
                Skill.deleted_at.is_(None),
            )
        )
    ).all()
    return [
        LinkedSkill(
            skill_id=s.id,
            name=s.name,
            category=s.category,
            proficiency=s.proficiency,
            usage_notes=link.usage_notes,
        )
        for link, s in rows
    ]


@router.post(
    "/work/{entity_id}/skills",
    response_model=LinkedSkill,
    status_code=status.HTTP_201_CREATED,
)
async def link_work_skill(
    entity_id: int,
    body: LinkSkillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LinkedSkill:
    await _get_owned(db, WorkExperience, entity_id, user.id)
    skill = await _skill_exists_for_user(db, body.skill_id, user.id)
    # Idempotent: if the link already exists, just update usage_notes.
    existing = (
        await db.execute(
            select(WorkExperienceSkill).where(
                WorkExperienceSkill.work_experience_id == entity_id,
                WorkExperienceSkill.skill_id == body.skill_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = WorkExperienceSkill(
            work_experience_id=entity_id,
            skill_id=body.skill_id,
            usage_notes=body.usage_notes,
        )
        db.add(existing)
    else:
        existing.usage_notes = body.usage_notes
    await db.commit()
    return LinkedSkill(
        skill_id=skill.id,
        name=skill.name,
        category=skill.category,
        proficiency=skill.proficiency,
        usage_notes=existing.usage_notes,
    )


@router.delete(
    "/work/{entity_id}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_work_skill(
    entity_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await _get_owned(db, WorkExperience, entity_id, user.id)
    row = (
        await db.execute(
            select(WorkExperienceSkill).where(
                WorkExperienceSkill.work_experience_id == entity_id,
                WorkExperienceSkill.skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


@router.get("/courses/{entity_id}/skills", response_model=list[LinkedSkill])
async def list_course_skills(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LinkedSkill]:
    await _get_owned_course(db, entity_id, user.id)
    rows = (
        await db.execute(
            select(CourseSkill, Skill)
            .join(Skill, CourseSkill.skill_id == Skill.id)
            .where(
                CourseSkill.course_id == entity_id,
                Skill.deleted_at.is_(None),
            )
        )
    ).all()
    return [
        LinkedSkill(
            skill_id=s.id,
            name=s.name,
            category=s.category,
            proficiency=s.proficiency,
            usage_notes=link.usage_notes,
        )
        for link, s in rows
    ]


@router.post(
    "/courses/{entity_id}/skills",
    response_model=LinkedSkill,
    status_code=status.HTTP_201_CREATED,
)
async def link_course_skill(
    entity_id: int,
    body: LinkSkillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LinkedSkill:
    await _get_owned_course(db, entity_id, user.id)
    skill = await _skill_exists_for_user(db, body.skill_id, user.id)
    existing = (
        await db.execute(
            select(CourseSkill).where(
                CourseSkill.course_id == entity_id,
                CourseSkill.skill_id == body.skill_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = CourseSkill(
            course_id=entity_id,
            skill_id=body.skill_id,
            usage_notes=body.usage_notes,
        )
        db.add(existing)
    else:
        existing.usage_notes = body.usage_notes
    await db.commit()
    return LinkedSkill(
        skill_id=skill.id,
        name=skill.name,
        category=skill.category,
        proficiency=skill.proficiency,
        usage_notes=existing.usage_notes,
    )


@router.delete(
    "/courses/{entity_id}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_course_skill(
    entity_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await _get_owned_course(db, entity_id, user.id)
    row = (
        await db.execute(
            select(CourseSkill).where(
                CourseSkill.course_id == entity_id,
                CourseSkill.skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


# --- Project skills (dedicated junction, mirrors Work/Course patterns) ------


async def _get_owned_project(
    db: AsyncSession, project_id: int, user_id: int
):
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.user_id == user_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/projects/{entity_id}/skills", response_model=list[LinkedSkill])
async def list_project_skills(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LinkedSkill]:
    await _get_owned_project(db, entity_id, user.id)
    rows = (
        await db.execute(
            select(ProjectSkill, Skill)
            .join(Skill, ProjectSkill.skill_id == Skill.id)
            .where(
                ProjectSkill.project_id == entity_id,
                Skill.deleted_at.is_(None),
            )
        )
    ).all()
    return [
        LinkedSkill(
            skill_id=s.id,
            name=s.name,
            category=s.category,
            proficiency=s.proficiency,
            usage_notes=link.usage_notes,
        )
        for link, s in rows
    ]


@router.post(
    "/projects/{entity_id}/skills",
    response_model=LinkedSkill,
    status_code=status.HTTP_201_CREATED,
)
async def link_project_skill(
    entity_id: int,
    body: LinkSkillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LinkedSkill:
    await _get_owned_project(db, entity_id, user.id)
    skill = await _skill_exists_for_user(db, body.skill_id, user.id)
    existing = (
        await db.execute(
            select(ProjectSkill).where(
                ProjectSkill.project_id == entity_id,
                ProjectSkill.skill_id == body.skill_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = ProjectSkill(
            project_id=entity_id,
            skill_id=body.skill_id,
            usage_notes=body.usage_notes,
        )
        db.add(existing)
    else:
        existing.usage_notes = body.usage_notes
    await db.commit()
    return LinkedSkill(
        skill_id=skill.id,
        name=skill.name,
        category=skill.category,
        proficiency=skill.proficiency,
        usage_notes=existing.usage_notes,
    )


@router.delete(
    "/projects/{entity_id}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_project_skill(
    entity_id: int,
    skill_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    await _get_owned_project(db, entity_id, user.id)
    row = (
        await db.execute(
            select(ProjectSkill).where(
                ProjectSkill.project_id == entity_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


# ============================================================================
# Generic entity links — polymorphic "related items" across all other history
# entities. Types are free-form strings validated against a known set.
# ============================================================================

# Types we permit on entity_links. Keep in sync with the frontend.
_LINKABLE_TYPES = {
    "work",
    "education",
    "course",
    "certification",
    "project",
    "publication",
    "presentation",
    "achievement",
    "volunteer",
    "language",
    "contact",
    "custom",
    "tracked_job",
    "skill",  # allowed too, though skill-specific tables are preferred
}


def _assert_linkable_type(t: str) -> str:
    if t not in _LINKABLE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown entity type '{t}'. Allowed: {sorted(_LINKABLE_TYPES)}",
        )
    return t


# Maps an entity type to (model, label_attr). Used to resolve labels for
# linked entries without fetching each one individually.
_TYPE_TO_MODEL: dict[str, tuple[type, str]] = {
    "work": (WorkExperience, "title"),
    "education": (Education, "institution"),  # overridden below via org name if available
    "course": (Course, "name"),
    "certification": (Certification, "name"),
    "project": (Project, "name"),
    "publication": (Publication, "title"),
    "presentation": (Presentation, "title"),
    "achievement": (Achievement, "title"),
    "volunteer": (VolunteerWork, "organization"),
    "language": (Language, "name"),
    "contact": (Contact, "name"),
    "custom": (CustomEvent, "title"),
    "skill": (Skill, "name"),
}


async def _verify_owns(
    db: AsyncSession, entity_type: str, entity_id: int, user_id: int
) -> None:
    """Ensure the user owns the referenced entity. Raises 404 otherwise."""
    if entity_type == "tracked_job":
        from app.models.jobs import TrackedJob
        stmt = select(TrackedJob).where(
            TrackedJob.id == entity_id,
            TrackedJob.user_id == user_id,
            TrackedJob.deleted_at.is_(None),
        )
    elif entity_type == "course":
        # Courses are owned transitively via Education.
        await _get_owned_course(db, entity_id, user_id)
        return
    else:
        model, _ = _TYPE_TO_MODEL[entity_type]
        # Soft-delete aware where possible.
        conditions = [model.id == entity_id, model.user_id == user_id]
        if hasattr(model, "deleted_at"):
            conditions.append(model.deleted_at.is_(None))
        stmt = select(model).where(*conditions)
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=404, detail=f"{entity_type} #{entity_id} not found"
        )


async def _label_for(
    db: AsyncSession, entity_type: str, entity_id: int
) -> Optional[str]:
    if entity_type == "tracked_job":
        from app.models.jobs import TrackedJob
        row = (
            await db.execute(select(TrackedJob.title).where(TrackedJob.id == entity_id))
        ).first()
        return row[0] if row else None
    if entity_type == "education":
        # Prefer organization name over the raw institution string.
        ed = (
            await db.execute(
                select(Education).where(Education.id == entity_id)
            )
        ).scalar_one_or_none()
        if ed is None:
            return None
        if ed.organization_id:
            org = (
                await db.execute(
                    select(Organization.name).where(Organization.id == ed.organization_id)
                )
            ).scalar_one_or_none()
            if org:
                suffix = (
                    f" · {ed.degree} {ed.field_of_study or ''}".strip()
                    if ed.degree
                    else ""
                )
                return f"{org}{suffix}"
        return ed.degree or "Education"
    model, attr = _TYPE_TO_MODEL[entity_type]
    row = (
        await db.execute(select(getattr(model, attr)).where(model.id == entity_id))
    ).first()
    return row[0] if row else None


@router.get("/links", response_model=list[EntityLinkOut])
async def list_entity_links(
    from_entity_type: Optional[str] = None,
    from_entity_id: Optional[int] = None,
    either_type: Optional[str] = None,
    either_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[EntityLinkOut]:
    """List entity_links owned by the current user.

    * `from_entity_type` + `from_entity_id` — only links that FROM this entity
      (one-directional, preserves original direction).
    * `either_type` + `either_id` — links where this entity is on EITHER
      side. The returned rows are normalized so the queried entity is always
      the `from_*` side and the counterpart is the `to_*` side, so the UI
      can render "linked from" context without extra bookkeeping.
    """
    from sqlalchemy import and_ as _and, or_ as _or

    stmt = select(EntityLink).where(EntityLink.user_id == user.id)

    # Either-direction mode takes precedence when both are supplied.
    if either_type is not None and either_id is not None:
        _assert_linkable_type(either_type)
        stmt = stmt.where(
            _or(
                _and(
                    EntityLink.from_entity_type == either_type,
                    EntityLink.from_entity_id == either_id,
                ),
                _and(
                    EntityLink.to_entity_type == either_type,
                    EntityLink.to_entity_id == either_id,
                ),
            )
        )
    else:
        if from_entity_type:
            _assert_linkable_type(from_entity_type)
            stmt = stmt.where(EntityLink.from_entity_type == from_entity_type)
        if from_entity_id is not None:
            stmt = stmt.where(EntityLink.from_entity_id == from_entity_id)

    stmt = stmt.order_by(EntityLink.id.desc())
    links = list((await db.execute(stmt)).scalars().all())

    # Hydrate `to_label` for the UI. In either-direction mode, also flip
    # reverse links so the queried entity is always on the `from_*` side.
    out: list[EntityLinkOut] = []
    for link in links:
        if (
            either_type is not None
            and either_id is not None
            and link.to_entity_type == either_type
            and link.to_entity_id == either_id
            and (
                link.from_entity_type != either_type
                or link.from_entity_id != either_id
            )
        ):
            # Reverse link — flip the sides so the queried entity is "from".
            from_type, from_id = link.to_entity_type, link.to_entity_id
            to_type, to_id = link.from_entity_type, link.from_entity_id
        else:
            from_type, from_id = link.from_entity_type, link.from_entity_id
            to_type, to_id = link.to_entity_type, link.to_entity_id
        label = None
        try:
            label = await _label_for(db, to_type, to_id)
        except Exception:
            pass
        out.append(
            EntityLinkOut(
                id=link.id,
                from_entity_type=from_type,
                from_entity_id=from_id,
                to_entity_type=to_type,
                to_entity_id=to_id,
                relation=link.relation,
                note=link.note,
                to_label=label,
            )
        )
    return out


@router.post(
    "/links",
    response_model=EntityLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity_link(
    payload: EntityLinkIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EntityLinkOut:
    _assert_linkable_type(payload.from_entity_type)
    _assert_linkable_type(payload.to_entity_type)
    if (
        payload.from_entity_type == payload.to_entity_type
        and payload.from_entity_id == payload.to_entity_id
    ):
        raise HTTPException(status_code=422, detail="Cannot link an entity to itself.")

    await _verify_owns(db, payload.from_entity_type, payload.from_entity_id, user.id)
    await _verify_owns(db, payload.to_entity_type, payload.to_entity_id, user.id)

    # Idempotent: if an identical link already exists, return it.
    existing = (
        await db.execute(
            select(EntityLink).where(
                EntityLink.user_id == user.id,
                EntityLink.from_entity_type == payload.from_entity_type,
                EntityLink.from_entity_id == payload.from_entity_id,
                EntityLink.to_entity_type == payload.to_entity_type,
                EntityLink.to_entity_id == payload.to_entity_id,
                EntityLink.relation == payload.relation,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = EntityLink(user_id=user.id, **payload.model_dump())
        db.add(existing)
        await db.commit()
        await db.refresh(existing)

    label = await _label_for(db, existing.to_entity_type, existing.to_entity_id)
    return EntityLinkOut(
        id=existing.id,
        from_entity_type=existing.from_entity_type,
        from_entity_id=existing.from_entity_id,
        to_entity_type=existing.to_entity_type,
        to_entity_id=existing.to_entity_id,
        relation=existing.relation,
        note=existing.note,
        to_label=label,
    )


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    link = (
        await db.execute(
            select(EntityLink).where(
                EntityLink.id == link_id, EntityLink.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    await db.delete(link)
    await db.commit()
