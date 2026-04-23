"""application-autofiller: given questions from an application form,
compose answers using the user's Preferences + WorkAuthorization + history.

Demographic fields are NEVER sent to the LLM as free text. If a question
looks demographic (pronouns, gender, race, DOB, veteran/disability status),
the LLM is instructed to return a curly-brace placeholder like `{pronouns}`;
the backend then substitutes the actual value from Demographics before
returning, and logs which fields were shared via AutofillLog.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.models.jobs import TrackedJob
from app.models.operational import AutofillLog
from app.models.preferences import (
    Demographics,
    JobPreferences,
    WorkAuthorization,
)
from app.models.user import User
from app.skills.runner import ClaudeCodeError, run_claude_prompt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/autofill", tags=["autofill"])


# Placeholder allow-list. Everything a template can resolve maps to a path in
# Demographics (first element) / WorkAuthorization / or composite.
_DEMOGRAPHIC_PLACEHOLDERS: dict[str, tuple[str, str]] = {
    "preferred_name": ("demographics", "preferred_name"),
    "legal_first_name": ("demographics", "legal_first_name"),
    "legal_middle_name": ("demographics", "legal_middle_name"),
    "legal_last_name": ("demographics", "legal_last_name"),
    "legal_suffix": ("demographics", "legal_suffix"),
    "full_name": ("demographics", "_full_name"),
    "pronouns": ("demographics", "pronouns"),
    "gender_identity": ("demographics", "gender_identity"),
    "sex_assigned_at_birth": ("demographics", "sex_assigned_at_birth"),
    "transgender_identification": ("demographics", "transgender_identification"),
    "sexual_orientation": ("demographics", "sexual_orientation"),
    "race_ethnicity": ("demographics", "race_ethnicity"),
    "veteran_status": ("demographics", "veteran_status"),
    "disability_status": ("demographics", "disability_status"),
    "accommodation_needs": ("demographics", "accommodation_needs"),
    "date_of_birth": ("demographics", "date_of_birth"),
    "age_bracket": ("demographics", "age_bracket"),
    "first_generation_college_student": (
        "demographics",
        "first_generation_college_student",
    ),
    "citizenship": ("auth", "citizenship_countries"),
    "work_auth_status": ("auth", "work_authorization_status"),
    "visa_type": ("auth", "visa_type"),
    "needs_sponsorship_now": ("auth", "visa_sponsorship_required_now"),
    "needs_sponsorship_future": ("auth", "visa_sponsorship_required_future"),
    "current_country": ("auth", "current_country"),
    "current_city": ("auth", "current_location_city"),
    "current_region": ("auth", "current_location_region"),
}


class AutofillIn(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=80)
    tracked_job_id: Optional[int] = None
    extra_notes: Optional[str] = None


class AutofillAnswer(BaseModel):
    question: str
    answer: Optional[str] = None
    placeholder_keys_used: list[str] = []
    skipped_reason: Optional[str] = None


class AutofillOut(BaseModel):
    answers: list[AutofillAnswer]
    fields_shared: list[str]
    warning: Optional[str] = None


_AUTOFILL_PROMPT = """You're filling out an application form for a job-seeker.

The user's JOB PREFERENCES (safe to reference):
{preferences}

WORK AUTHORIZATION (mostly safe to reference, but use placeholders for the
visa dates themselves so the backend can format them consistently):
{authorization}

TRACKED JOB being applied to (may be null):
{job}

User's extra notes for this run (optional):
{extra_notes}

QUESTIONS:
{questions_numbered}

Rules
-----
1. Answer each question concretely and briefly.
2. For DEMOGRAPHIC questions (name, pronouns, gender, sex, orientation, race,
   veteran/disability status, date of birth, age bracket, first-gen,
   accommodation needs) you MUST NOT make up a value. Instead return a
   placeholder token like `{{pronouns}}` or `{{preferred_name}}`. The allowed
   placeholder keys are: {placeholder_keys}.
3. For visa-type + sponsorship questions also use placeholders so the
   backend substitutes consistent formatting: `{{visa_type}}`,
   `{{needs_sponsorship_now}}`, `{{needs_sponsorship_future}}`, `{{citizenship}}`,
   `{{work_auth_status}}`, `{{current_country}}`, `{{current_city}}`,
   `{{current_region}}`.
4. For yes/no questions about preferences (salary range, relocation
   willingness, start date), answer directly from JOB PREFERENCES.
5. If a question is genuinely not answerable from the data the user has
   provided, return null for `answer` and fill `skipped_reason` with a
   one-sentence explanation.
6. Return ONE JSON object, no prose, no markdown fences:

{{
  "answers": [
    {{
      "question_index": number,
      "answer": string | null,
      "placeholder_keys_used": string[],
      "skipped_reason": string | null
    }}
  ],
  "warning": string | null
}}
"""


def _full_name(d: Optional[Demographics]) -> Optional[str]:
    if d is None:
        return None
    parts = [d.legal_first_name, d.legal_middle_name, d.legal_last_name, d.legal_suffix]
    s = " ".join(p for p in parts if p)
    return s or d.preferred_name or None


def _bool_label(v: Any) -> Optional[str]:
    if v is True:
        return "Yes"
    if v is False:
        return "No"
    return None


def _format_placeholder(
    key: str, demo: Optional[Demographics], auth: Optional[WorkAuthorization]
) -> tuple[Optional[str], bool]:
    """Return (substitution_string, was_resolved)."""
    spec = _DEMOGRAPHIC_PLACEHOLDERS.get(key)
    if spec is None:
        return None, False
    kind, attr = spec
    if kind == "demographics" and demo is not None:
        if attr == "_full_name":
            return _full_name(demo), True
        v = getattr(demo, attr, None)
        if v is None:
            return None, False
        if isinstance(v, list):
            return ", ".join(str(x) for x in v), True
        if hasattr(v, "isoformat"):
            return v.isoformat(), True
        return str(v), True
    if kind == "auth" and auth is not None:
        v = getattr(auth, attr, None)
        if v is None:
            return None, False
        if isinstance(v, list):
            return ", ".join(str(x) for x in v), True
        if isinstance(v, bool):
            return _bool_label(v), True
        return str(v), True
    return None, False


_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
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


@router.post("", response_model=AutofillOut)
async def autofill(
    payload: AutofillIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AutofillOut:
    prefs = (
        await db.execute(
            select(JobPreferences).where(
                JobPreferences.user_id == user.id,
                JobPreferences.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    auth = (
        await db.execute(
            select(WorkAuthorization).where(
                WorkAuthorization.user_id == user.id,
                WorkAuthorization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    demo = (
        await db.execute(
            select(Demographics).where(
                Demographics.user_id == user.id,
                Demographics.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    job: Optional[TrackedJob] = None
    if payload.tracked_job_id:
        job = (
            await db.execute(
                select(TrackedJob).where(
                    TrackedJob.id == payload.tracked_job_id,
                    TrackedJob.user_id == user.id,
                    TrackedJob.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Tracked job not found")

    # Prepare prompt inputs. Note: Demographics is intentionally OMITTED from
    # the prompt — the LLM must use placeholders for demographic questions.
    def _safe_dump(model: Any, exclude: set[str] | None = None) -> str:
        if model is None:
            return "(none)"
        out = {}
        for c in model.__table__.columns:
            if exclude and c.name in exclude:
                continue
            v = getattr(model, c.name, None)
            if v is None:
                continue
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            out[c.name] = v
        return json.dumps(out, indent=2) if out else "(empty)"

    prefs_str = _safe_dump(prefs, exclude={"id", "user_id", "created_at", "updated_at", "deleted_at"})
    # Strip visa dates from auth dump so LLM uses placeholders.
    auth_str = _safe_dump(
        auth,
        exclude={
            "id", "user_id", "created_at", "updated_at", "deleted_at",
            "visa_issued_date", "visa_expires_date",
        },
    )
    job_str = (
        json.dumps(
            {
                "title": job.title,
                "status": job.status,
                "location": job.location,
                "remote_policy": job.remote_policy,
                "employment_type": job.employment_type,
                "experience_level": job.experience_level,
            },
            indent=2,
        )
        if job
        else "(no tracked job)"
    )
    questions_numbered = "\n".join(
        f"{i}. {q}" for i, q in enumerate(payload.questions, 1)
    )

    prompt = _AUTOFILL_PROMPT.format(
        preferences=prefs_str,
        authorization=auth_str,
        job=job_str,
        extra_notes=payload.extra_notes or "(none)",
        questions_numbered=questions_numbered,
        placeholder_keys=", ".join(sorted(_DEMOGRAPHIC_PLACEHOLDERS.keys())),
    )

    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source="autofill",
            item_id=f"autofill:{user.id}:{int(__import__('time').time())}",
            label=f"Autofill ({len(payload.questions)} q)",
            allowed_tools=[],
            timeout_seconds=120,
        )
    except ClaudeCodeError as exc:
        log.warning("autofill failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json(final_text) or {}
    raw_answers = data.get("answers") or []

    # Build response, resolving placeholders.
    fields_shared: set[str] = set()
    resolved: dict[int, AutofillAnswer] = {}
    for entry in raw_answers:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("question_index")
        if not isinstance(idx, int) or idx < 1 or idx > len(payload.questions):
            continue
        answer = entry.get("answer")
        keys_used: list[str] = []
        if isinstance(answer, str):
            def _sub(m: re.Match) -> str:
                key = m.group(1)
                value, ok = _format_placeholder(key, demo, auth)
                if ok and value is not None:
                    keys_used.append(key)
                    fields_shared.add(key)
                    return value
                return m.group(0)  # leave unresolved placeholder visible

            answer = _PLACEHOLDER_RE.sub(_sub, answer)
        resolved[idx] = AutofillAnswer(
            question=payload.questions[idx - 1],
            answer=answer if isinstance(answer, str) or answer is None else str(answer),
            placeholder_keys_used=keys_used,
            skipped_reason=entry.get("skipped_reason"),
        )

    # Any question the model skipped silently — fill in a stub.
    for i, q in enumerate(payload.questions, 1):
        if i not in resolved:
            resolved[i] = AutofillAnswer(
                question=q, answer=None, skipped_reason="No answer returned."
            )

    # Log what was shared so the user has an auditable trail.
    if fields_shared:
        db.add(
            AutofillLog(
                user_id=user.id,
                tracked_job_id=payload.tracked_job_id,
                fields_shared=sorted(fields_shared),
                recipient=(job.title if job else None),
            )
        )
        await db.commit()

    ordered = [resolved[i] for i in sorted(resolved.keys())]
    return AutofillOut(
        answers=ordered,
        fields_shared=sorted(fields_shared),
        warning=data.get("warning"),
    )
