"""JSON export / import of all user-owned data."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect as sa_inspect

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.base import Base
from app.models.companion import CompanionConversation, ConversationMessage
from app.models.documents import GeneratedDocument, WritingSample
from app.models.history import (
    Achievement, Certification, Contact, Course, CustomEvent, Education,
    Language, Presentation, Project, ProjectSkill, Publication, Skill,
    VolunteerWork, WorkExperience, WorkExperienceSkill, CourseSkill,
)
from app.models.jobs import (
    ApplicationEvent, InterviewArtifact, InterviewRound, JobFetchQueue,
    TrackedJob,
)
from app.models.links import EntityLink
from app.models.preferences import (
    Demographics, JobCriterion, JobPreferences, WorkAuthorization,
)
from app.models.user import Persona, User

router = APIRouter(prefix="/admin", tags=["data-io"])


# Every model class whose rows we export, in FK-safe insert order.
USER_MODELS = [
    Persona, JobPreferences, JobCriterion, WorkAuthorization, Demographics,
    Skill, WorkExperience, Education, Course, Certification, Language,
    Project, Publication, Presentation, Achievement, VolunteerWork, Contact,
    CustomEvent, WorkExperienceSkill, CourseSkill, ProjectSkill, EntityLink,
    TrackedJob, InterviewRound, ApplicationEvent, InterviewArtifact, JobFetchQueue,
    GeneratedDocument, WritingSample,
    CompanionConversation, ConversationMessage,
]


def _serialize(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        # SQLAlchemy Numeric columns come back as Decimal; json won't take
        # them natively. Export as float for readability — import can
        # round-trip through SQLAlchemy's Numeric type coercion.
        return float(v)
    return v


def _row_to_dict(row: Any) -> dict:
    return {
        c.key: _serialize(getattr(row, c.key))
        for c in sa_inspect(row.__class__).mapper.column_attrs
    }


async def _rows_for(db: AsyncSession, model: type, user_id: int) -> list[dict]:
    """Pull this model's rows that belong to the user (direct or transitive)."""
    if hasattr(model, "user_id"):
        stmt = select(model).where(model.user_id == user_id)
    elif model is ConversationMessage:
        stmt = select(model).join(
            CompanionConversation,
            CompanionConversation.id == ConversationMessage.conversation_id,
        ).where(CompanionConversation.user_id == user_id)
    elif model is Course:
        stmt = select(model).join(
            Education, Education.id == Course.education_id
        ).where(Education.user_id == user_id)
    elif model is InterviewRound or model is ApplicationEvent or model is InterviewArtifact:
        stmt = select(model).join(
            TrackedJob, TrackedJob.id == model.tracked_job_id
        ).where(TrackedJob.user_id == user_id)
    elif model is WorkExperienceSkill:
        stmt = select(model).join(
            WorkExperience, WorkExperience.id == WorkExperienceSkill.work_experience_id
        ).where(WorkExperience.user_id == user_id)
    elif model is CourseSkill:
        stmt = select(model).join(
            Course, Course.id == CourseSkill.course_id
        ).join(Education, Education.id == Course.education_id).where(
            Education.user_id == user_id
        )
    elif model is ProjectSkill:
        stmt = select(model).join(
            Project, Project.id == ProjectSkill.project_id
        ).where(Project.user_id == user_id)
    else:
        return []
    rows = (await db.execute(stmt)).scalars().all()
    return [_row_to_dict(r) for r in rows]


@router.get("/export")
async def export_all(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Download a full JSON dump of everything this user owns."""
    payload: dict[str, Any] = {
        "format_version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "user": _row_to_dict(user),
        "tables": {},
    }
    for m in USER_MODELS:
        payload["tables"][m.__tablename__] = await _rows_for(db, m, user.id)
    body = json.dumps(payload, indent=2).encode("utf-8")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="jsp-export-{user.id}-{ts}.json"',
        },
    )


@router.post("/import")
async def import_all(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Import rows from a previously exported dump.

    Only inserts: never overwrites existing data. Primary keys and foreign
    keys are remapped so imported rows always get fresh ids. User-scoped FKs
    are reassigned to the current user's id.
    """
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=422, detail="Not valid JSON.")
    tables = payload.get("tables") or {}

    by_name = {m.__tablename__: m for m in USER_MODELS}
    # Map of (table_name, old_id) → new_id for FK remapping.
    id_map: dict[tuple[str, int], int] = {}
    # Columns that reference another table by id — (col_name → target_table).
    # We use SQLAlchemy's FK inspection for this.
    created = {}

    for m in USER_MODELS:
        tbl = m.__tablename__
        rows = tables.get(tbl) or []
        if not rows:
            continue
        cols = {c.key for c in sa_inspect(m).mapper.column_attrs}
        fk_map: dict[str, str] = {}
        for col in m.__table__.columns:
            if col.foreign_keys:
                for fk in col.foreign_keys:
                    fk_map[col.name] = fk.column.table.name
                    break
        created[tbl] = 0
        for row in rows:
            data = {k: v for k, v in row.items() if k in cols and k not in ("id", "created_at", "updated_at")}
            if "user_id" in cols:
                data["user_id"] = user.id
            for col_name, target_tbl in fk_map.items():
                if col_name == "user_id":
                    continue
                if col_name in data and data[col_name] is not None:
                    new = id_map.get((target_tbl, data[col_name]))
                    if new is not None:
                        data[col_name] = new
                    else:
                        # Missing ref — null it out so the insert doesn't fail.
                        data[col_name] = None
            obj = m(**data)
            db.add(obj)
            try:
                await db.flush()
            except Exception:
                await db.rollback()
                continue
            old_id = row.get("id")
            if old_id is not None:
                id_map[(tbl, old_id)] = obj.id
            created[tbl] += 1
    await db.commit()
    return {"imported": created}
