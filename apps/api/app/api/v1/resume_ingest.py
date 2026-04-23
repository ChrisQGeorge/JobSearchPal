"""Resume-ingest skill: parse an uploaded resume and propose / create
WorkExperience, Education, Skill, and Project rows.

Two-step flow:
  POST /history/resume-ingest?dry_run=1  — analyze only, return proposals
  POST /history/resume-ingest?dry_run=0  — create the entities for real

The caller hands us a `document_id` of a previously-uploaded document (so
we reuse the existing doc_text extraction pipeline for PDF/DOCX/HTML). The
LLM is instructed to emit structured JSON only; no free-text prose.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.documents import GeneratedDocument
from app.models.history import (
    Education,
    Project,
    Skill,
    WorkExperience,
    WorkExperienceSkill,
)
from app.models.jobs import Organization
from app.models.user import User
from app.skills.runner import ClaudeCodeError, run_claude_prompt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/history", tags=["resume-ingest"])


_INGEST_PROMPT = """You are extracting structured history from a resume the
user uploaded. Return ONLY a JSON object matching the schema below. Do not
paraphrase bullet points — preserve the user's own wording where possible.

Resume text:
---
{body}
---

Return schema (no prose, no code fences):

{{
  "work_experiences": [
    {{
      "title": string,
      "organization_name": string | null,
      "location": string | null,
      "start_date": "YYYY-MM-DD" | null,  // infer YYYY-MM-01 from "May 2021"
      "end_date": "YYYY-MM-DD" | null,    // null if ongoing / "Present"
      "employment_type": "full_time" | "part_time" | "contract" | "c2h" | "internship" | "freelance" | null,
      "remote_policy": "onsite" | "hybrid" | "remote" | null,
      "summary": string | null,           // 1-3 sentences of what the role was
      "highlights": string[],             // bullet points, verbatim
      "technologies_used": string[]       // specific tech / tools mentioned
    }}
  ],
  "educations": [
    {{
      "organization_name": string | null,  // the school
      "degree": string | null,
      "field_of_study": string | null,
      "concentration": string | null,
      "start_date": "YYYY-MM-DD" | null,
      "end_date": "YYYY-MM-DD" | null,
      "gpa": number | null,
      "honors": string[],
      "notes": string | null
    }}
  ],
  "skills": string[],                      // flat list of canonical skills
  "projects": [
    {{
      "name": string,
      "role": string | null,
      "summary": string | null,
      "url": string | null,
      "repo_url": string | null,
      "start_date": "YYYY-MM-DD" | null,
      "end_date": "YYYY-MM-DD" | null,
      "is_ongoing": boolean,
      "technologies_used": string[]
    }}
  ],
  "warning": string | null                 // honest caveats — missing dates,
                                           // illegible section, etc.
}}

Rules:
- Prefer null over guesses. If a month is absent, pick Jan of the stated year.
- For skills, produce canonical short names ("Python", "React", "AWS") — one
  entry per distinct tech, no duplicates (case-insensitive).
- Never invent entries the resume doesn't clearly show.
"""


_JSON_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        inner = "\n".join(text.splitlines()[1:]).rsplit("```", 1)[0]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


class IngestIn(BaseModel):
    document_id: int
    dry_run: bool = True


class IngestOut(BaseModel):
    proposals: dict
    warning: Optional[str] = None
    created: Optional[dict] = None  # present only on dry_run=False


async def _resolve_or_create_org(
    db: AsyncSession, name: Optional[str], org_type: str
) -> Optional[int]:
    if not name or not name.strip():
        return None
    cleaned = name.strip()
    existing = (
        await db.execute(
            select(Organization).where(
                func.lower(Organization.name) == cleaned.lower(),
                Organization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    org = Organization(name=cleaned, type=org_type)
    db.add(org)
    await db.flush()
    return org.id


async def _find_or_create_skill(
    db: AsyncSession, user_id: int, name: str
) -> Optional[Skill]:
    n = (name or "").strip()
    if not n:
        return None
    existing = (
        await db.execute(
            select(Skill).where(
                Skill.user_id == user_id,
                Skill.deleted_at.is_(None),
                func.lower(Skill.name) == n.lower(),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    s = Skill(user_id=user_id, name=n)
    db.add(s)
    await db.flush()
    return s


def _parse_date(v: Any):
    if not v:
        return None
    try:
        return datetime.strptime(str(v), "%Y-%m-%d").date()
    except ValueError:
        return None


@router.post("/resume-ingest", response_model=IngestOut)
async def resume_ingest(
    payload: IngestIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestOut:
    # Load the uploaded document; it must belong to the user.
    doc = (
        await db.execute(
            select(GeneratedDocument).where(
                GeneratedDocument.id == payload.document_id,
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    body = (doc.content_md or "").strip()
    if not body:
        raise HTTPException(
            status_code=422,
            detail="Document has no extractable text — ingest can't read it.",
        )

    prompt = _INGEST_PROMPT.format(body=body[:80_000])

    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source="resume_ingest",
            item_id=f"ingest:{doc.id}",
            label=f"Resume ingest: {doc.title}",
            allowed_tools=[],
            timeout_seconds=180,
        )
    except ClaudeCodeError as exc:
        log.warning("resume-ingest failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json(final_text) or {}
    proposals = {
        "work_experiences": data.get("work_experiences") or [],
        "educations": data.get("educations") or [],
        "skills": data.get("skills") or [],
        "projects": data.get("projects") or [],
    }
    warning = data.get("warning")

    if payload.dry_run:
        return IngestOut(proposals=proposals, warning=warning)

    # Persist.
    created = {"work_experiences": 0, "educations": 0, "skills": 0, "projects": 0}

    # Skills first so we can link them to work rows.
    skill_map: dict[str, int] = {}
    for name in proposals["skills"]:
        if not isinstance(name, str):
            continue
        s = await _find_or_create_skill(db, user.id, name)
        if s is not None:
            skill_map[name.strip().lower()] = s.id
            if s.id:
                created["skills"] += 1  # (may count existing too — acceptable)

    for w in proposals["work_experiences"]:
        if not isinstance(w, dict):
            continue
        title = (w.get("title") or "").strip()
        if not title:
            continue
        org_id = await _resolve_or_create_org(db, w.get("organization_name"), "company")
        wex = WorkExperience(
            user_id=user.id,
            organization_id=org_id,
            title=title,
            location=w.get("location") or None,
            employment_type=w.get("employment_type") or None,
            remote_policy=w.get("remote_policy") or None,
            start_date=_parse_date(w.get("start_date")),
            end_date=_parse_date(w.get("end_date")),
            summary=w.get("summary") or None,
            highlights=w.get("highlights") or None,
            technologies_used=w.get("technologies_used") or None,
        )
        db.add(wex)
        await db.flush()
        created["work_experiences"] += 1
        # Link any technologies_used that already exist as skills.
        for tech in (w.get("technologies_used") or []):
            if not isinstance(tech, str):
                continue
            sid = skill_map.get(tech.strip().lower())
            if sid is None:
                s = await _find_or_create_skill(db, user.id, tech)
                if s is not None:
                    skill_map[tech.strip().lower()] = s.id
                    sid = s.id
            if sid:
                # Avoid duplicates.
                exists = (
                    await db.execute(
                        select(WorkExperienceSkill).where(
                            WorkExperienceSkill.work_experience_id == wex.id,
                            WorkExperienceSkill.skill_id == sid,
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    db.add(
                        WorkExperienceSkill(work_experience_id=wex.id, skill_id=sid)
                    )

    for e in proposals["educations"]:
        if not isinstance(e, dict):
            continue
        org_id = await _resolve_or_create_org(
            db, e.get("organization_name"), "university"
        )
        ed = Education(
            user_id=user.id,
            organization_id=org_id,
            degree=e.get("degree") or None,
            field_of_study=e.get("field_of_study") or None,
            concentration=e.get("concentration") or None,
            start_date=_parse_date(e.get("start_date")),
            end_date=_parse_date(e.get("end_date")),
            gpa=e.get("gpa") if isinstance(e.get("gpa"), (int, float)) else None,
            honors=e.get("honors") or None,
            notes=e.get("notes") or None,
        )
        db.add(ed)
        await db.flush()
        created["educations"] += 1

    for p in proposals["projects"]:
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        if not name:
            continue
        proj = Project(
            user_id=user.id,
            name=name,
            role=p.get("role") or None,
            summary=p.get("summary") or None,
            url=p.get("url") or None,
            repo_url=p.get("repo_url") or None,
            start_date=_parse_date(p.get("start_date")),
            end_date=_parse_date(p.get("end_date")),
            is_ongoing=bool(p.get("is_ongoing")) if p.get("is_ongoing") is not None else False,
            technologies_used=p.get("technologies_used") or None,
            visibility="private",
        )
        db.add(proj)
        await db.flush()
        created["projects"] += 1

    await db.commit()
    return IngestOut(proposals=proposals, warning=warning, created=created)
