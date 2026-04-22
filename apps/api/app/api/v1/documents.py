"""Generated documents: resume tailoring, cover letters, etc.

The "tailor" endpoint kicks off a Claude Code run that pulls the user's
history via the same curl-accessible API used by the Companion, reads the
stored job description, and writes a tailored document back to the
generated_documents table. The document is returned so the UI can show it
immediately.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.models.documents import DocumentEdit, GeneratedDocument, WritingSample
from app.models.jobs import TrackedJob
from app.models.user import User
from app.skills.runner import ClaudeCodeError, run_claude_prompt

log = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


DOC_TYPES = {
    "resume",
    "cover_letter",
    "outreach_email",
    "thank_you",
    "followup",
    "portfolio",
    "offer_letter",
    "reference",
    "transcript",
    "certificate",
    "other",
}


# Anything above this is rejected outright — uploads live in a shared volume.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per file
UPLOADS_ROOT = Path("/app/uploads")


def _user_uploads_dir(user_id: int) -> Path:
    d = UPLOADS_ROOT / "documents" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitize_filename(name: str) -> str:
    # Strip paths, keep only safe chars.
    name = Path(name).name
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name[:120] or "upload"


class GeneratedDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tracked_job_id: Optional[int] = None
    doc_type: str
    title: str
    content_md: Optional[str] = None
    content_structured: Optional[Any] = None
    version: int
    parent_version_id: Optional[int] = None
    humanized: bool
    model_used: Optional[str] = None
    persona_id: Optional[int] = None
    source_skill: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TailorResumeIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    extra_notes: Optional[str] = None  # free-form user guidance piped into the prompt
    persona_id: Optional[int] = None


class TailorCoverLetterIn(TailorResumeIn):
    pass


_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def _extract_json_object(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        inner = "\n".join(text.splitlines()[1:])
        if inner.rstrip().endswith("```"):
            inner = inner.rsplit("```", 1)[0]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    m = _JSON_OBJECT_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


async def _get_owned_job(
    db: AsyncSession, job_id: int, user_id: int
) -> TrackedJob:
    stmt = select(TrackedJob).where(
        TrackedJob.id == job_id,
        TrackedJob.user_id == user_id,
        TrackedJob.deleted_at.is_(None),
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _get_owned_document(
    db: AsyncSession, doc_id: int, user_id: int
) -> GeneratedDocument:
    stmt = select(GeneratedDocument).where(
        GeneratedDocument.id == doc_id,
        GeneratedDocument.user_id == user_id,
        GeneratedDocument.deleted_at.is_(None),
    )
    doc = (await db.execute(stmt)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


# --- CRUD -------------------------------------------------------------------


class ManualCreateIn(BaseModel):
    doc_type: str = Field(description="One of DOC_TYPES.")
    title: str = Field(min_length=1, max_length=255)
    tracked_job_id: Optional[int] = None
    content_md: Optional[str] = None


@router.post(
    "",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_manual(
    payload: ManualCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    """Create a GeneratedDocument from scratch — no tailor, no upload.

    Lets the user start a blank resume / note / reference doc in the Studio
    and write it themselves. Optional tracked_job_id attaches it to a job;
    otherwise it lives in the "Unaffiliated" bucket of the Studio list.
    """
    if payload.doc_type not in DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown doc_type '{payload.doc_type}'. Allowed: {sorted(DOC_TYPES)}",
        )
    if payload.tracked_job_id is not None:
        await _get_owned_job(db, payload.tracked_job_id, user.id)

    # Version per (user, tracked_job_id, doc_type).
    prev_row = (
        await db.execute(
            select(GeneratedDocument.id, GeneratedDocument.version)
            .where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.tracked_job_id == payload.tracked_job_id,
                GeneratedDocument.doc_type == payload.doc_type,
                GeneratedDocument.deleted_at.is_(None),
            )
            .order_by(GeneratedDocument.version.desc())
            .limit(1)
        )
    ).first()
    next_version = (prev_row[1] + 1) if prev_row else 1
    parent_version_id = prev_row[0] if prev_row else None

    doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=payload.tracked_job_id,
        doc_type=payload.doc_type,
        title=payload.title.strip()[:255],
        content_md=payload.content_md,
        content_structured={"source": "manual"},
        version=next_version,
        parent_version_id=parent_version_id,
        humanized=False,
        source_skill="manual",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("", response_model=list[GeneratedDocumentOut])
async def list_documents(
    tracked_job_id: Optional[int] = None,
    doc_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GeneratedDocument]:
    stmt = (
        select(GeneratedDocument)
        .where(
            GeneratedDocument.user_id == user.id,
            GeneratedDocument.deleted_at.is_(None),
        )
        .order_by(GeneratedDocument.created_at.desc())
    )
    if tracked_job_id is not None:
        stmt = stmt.where(GeneratedDocument.tracked_job_id == tracked_job_id)
    if doc_type is not None:
        stmt = stmt.where(GeneratedDocument.doc_type == doc_type)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{doc_id:int}", response_model=GeneratedDocumentOut)
async def get_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    return await _get_owned_document(db, doc_id, user.id)


class GeneratedDocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    content_md: Optional[str] = None


@router.put("/{doc_id:int}", response_model=GeneratedDocumentOut)
async def update_document(
    doc_id: int,
    payload: GeneratedDocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    doc = await _get_owned_document(db, doc_id, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(doc, k, v)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.delete("/{doc_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    doc = await _get_owned_document(db, doc_id, user.id)
    doc.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


# --- Tailoring --------------------------------------------------------------

_TAILOR_RESUME_PROMPT = """You are tailoring a professional resume for a specific
job. The user already has their full work/education/skills history saved in
this app — you MUST pull it via the API before writing. Do not invent
anything; everything in the resume must come from fetched data.

The base URL and bearer token are in environment variables JSP_API_BASE_URL
and JSP_API_TOKEN. Endpoints (all JSON, auth via `Authorization: Bearer $JSP_API_TOKEN`):

  GET  $JSP_API_BASE_URL/api/v1/auth/me                       (login identity: email, display_name)
  GET  $JSP_API_BASE_URL/api/v1/preferences/demographics      (preferred_name, legal names, pronouns)
  GET  $JSP_API_BASE_URL/api/v1/preferences/authorization     (current_location_city, current_location_region)
  GET  $JSP_API_BASE_URL/api/v1/history/work
  GET  $JSP_API_BASE_URL/api/v1/history/education
  GET  $JSP_API_BASE_URL/api/v1/history/skills
  GET  $JSP_API_BASE_URL/api/v1/history/projects
  GET  $JSP_API_BASE_URL/api/v1/history/certifications
  GET  $JSP_API_BASE_URL/api/v1/history/publications
  GET  $JSP_API_BASE_URL/api/v1/history/achievements

Fetch in parallel with curl, e.g.:

  curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" \\
       "$JSP_API_BASE_URL/api/v1/history/work"

Target job
----------
Title:        {title}
Organization: {organization}
Location:     {location}

Job description (verbatim):

---
{job_description}
---

Required skills: {required_skills}
Nice to have:    {nice_to_have_skills}

Existing fit analysis (if present, honour its resume_emphasis and prioritized skills):

{jd_analysis_blob}

User-supplied guidance for THIS tailoring run (if any — weight these heavily):

{extra_notes}

What a polished resume looks like
---------------------------------
Follow this structure exactly. Use real content only; omit sections whose
data you couldn't find. Prefer en-dashes (–) for date ranges, em-dashes (—)
between header fields, and bullet characters in markdown lists (`- `).

# {{Candidate Full Name}}
{{City, Region}} · {{email}} · {{phone if on file}} · {{linkedin/site if on file}}

## Professional Summary

Three to four sentences, written in confident third-person-implied style
(no "I"), tying the candidate's real background to THIS job. Lead with
years-of-experience framing ("Senior engineer with N years…"), then name
the two or three most relevant domains/skills, then close with a concrete
impact claim pulled from their highlights. No fluff, no "passionate about".

## Core Skills

Grouped into 3–5 categories (e.g. "Languages", "Cloud & Infra", "Data").
Each category rendered as a single line:

- **Languages:** Python, TypeScript, Go, SQL
- **Cloud & Infra:** AWS (ECS, Lambda), Terraform, Docker, Kubernetes
- **Data:** PostgreSQL, Redis, Kafka, dbt

Only include skills the user actually has on file. Prioritize items also
mentioned in the JD's required/nice-to-have lists.

## Professional Experience

For each relevant role, render this exact pattern (do NOT drop any lines):

### {{Role title}} — {{Organization}}
*{{City, Region}} · {{Start Month YYYY}} – {{End Month YYYY or Present}}*

One-sentence role scope (what the team did, what the role owned). Optional
if highlights are strong enough to stand alone.

- Achievement bullet: start with a strong verb (Led, Shipped, Reduced,
  Architected, Scaled…). Quantify with real metrics from the user's
  highlights when available. Name the technology used.
- Keep 3–5 bullets per role, 6 max for the most recent / most relevant one.
  Trim less relevant roles to 2 bullets. Never invent metrics.
- Bullets should be one line each in the source markdown (no line wraps
  mid-bullet); commas/semicolons are fine for readability.

List roles reverse-chronologically. Include every role the user has on
file, but scale depth to relevance: the most JD-relevant roles get the
most bullets; older or off-topic roles can compress to a single summary
bullet.

## Education

### {{Degree, Field}} — {{Institution}}
*{{City, Region}} · {{Start YYYY}} – {{End YYYY or Expected YYYY}}*

One optional line: concentration, GPA if ≥3.5 and on file, or standout
coursework if directly relevant to the JD.

## Projects  *(include ONLY if the user has project entries AND at least one is relevant)*

### {{Project name}}
*{{Technologies}} · {{Year(s)}}*

- 1–3 bullets. Same verb-first, quantified style as Experience.

## Certifications  *(include ONLY if on file)*

- {{Certification}} — {{Issuer}}, {{Year}}

## Publications / Achievements  *(include ONLY if on file and credible)*

- {{Title}} — {{Venue}}, {{Year}}

Rules
-----
- NEVER invent experience, skills, companies, dates, metrics, accomplishments,
  phone numbers, or links. If a field is missing on file, omit it rather than
  make one up. If contact info is thin, use only what's there.
- Reorder and rephrase to foreground JD relevance. Rephrase stored highlights
  into tight, verb-led resume bullets — but do not fabricate metrics that
  aren't present in the source.
- Target length: one dense page (roughly 450–650 words of markdown body,
  not counting headers). If the user's data supports more, lean toward
  1.5 pages for senior candidates; never pad.
- Use consistent date formatting throughout: `Month YYYY – Month YYYY`,
  or `YYYY – YYYY` if only year is on file, or `… – Present` for current.
- Capitalize proper nouns exactly as stored (AWS, PostgreSQL, Kubernetes).
- Never include demographic data (pronouns, age, ethnicity, veteran status)
  on the resume. Those endpoints are only useful for name and location.
- If the user's stored data is too thin for a credible resume, set `warning`
  explaining what's missing and produce the honest subset you can.

Return ONE JSON object, no prose, no markdown fences around the JSON:

{{
  "title": string,          // e.g. "Resume – Acme Senior Engineer"
  "content_md": string,     // the full resume in Markdown, following the structure above
  "notes": string,          // 1–2 sentences on what you emphasized and trimmed
  "warning": string | null  // honest caveats (missing phone, no dated roles, etc.)
}}
"""


_TAILOR_COVER_LETTER_PROMPT = """You are writing a polished, human-sounding
cover letter for a specific job. The user's full history is behind the same
API — pull what you need before writing.

Environment: $JSP_API_BASE_URL and $JSP_API_TOKEN (bearer). Endpoints:

  GET  $JSP_API_BASE_URL/api/v1/auth/me                    (email, display_name)
  GET  $JSP_API_BASE_URL/api/v1/preferences/demographics   (preferred_name, legal names)
  GET  $JSP_API_BASE_URL/api/v1/preferences/authorization  (current_location_city, _region)
  GET  $JSP_API_BASE_URL/api/v1/history/work
  GET  $JSP_API_BASE_URL/api/v1/history/skills
  GET  $JSP_API_BASE_URL/api/v1/history/projects
  GET  $JSP_API_BASE_URL/api/v1/history/achievements

Target job
----------
Title:        {title}
Organization: {organization}

Job description (verbatim):

---
{job_description}
---

Existing fit analysis (cover_letter_hook is especially useful):

{jd_analysis_blob}

User guidance for THIS letter (optional but take seriously):

{extra_notes}

What a polished cover letter looks like
---------------------------------------
Follow this structure exactly. Render in Markdown using the layout below —
preview will style it as a formal business letter.

**{{Candidate Full Name}}**
{{City, Region}} · {{email}}
{{Today's date, spelled out: e.g. "April 22, 2026"}}

**{{Hiring Manager or "Hiring Team"}}**
{{Organization}}

---

Dear {{Hiring Manager name if known, otherwise "Hiring Team"}},

Paragraph 1 — The hook (3–5 sentences). Open with something concrete about
the role, team, product, or a stated value from the posting. State the role
you're applying to and the single strongest reason you're a fit (drawn from
real history). Avoid "I am writing to express my interest" and "I am a
passionate…". Warm, direct, first person.

Paragraph 2 — Proof, act one (4–6 sentences). Pick the single most
JD-relevant experience from their history and tell a tight mini-story:
what the challenge was, what they did, what shipped. Name the technology
and the scale (team size, traffic, scope) when it's in the stored data.
Tie it back to a specific need in the JD by paraphrasing — don't quote
the posting verbatim.

Paragraph 3 — Proof, act two (3–5 sentences). A second story or a tight
cluster of 2–3 related credentials covering a different dimension of the
role (e.g. if paragraph 2 was technical depth, this one shows leadership
or cross-functional collaboration). Again, only real content.

Paragraph 4 — Close (2–3 sentences). Forward-looking: what excites them
about this specific company/product/team, and a concrete next step
("Happy to walk through any of this in an interview"). No clichés like
"Thank you for considering my application".

Sincerely,
{{Candidate Full Name}}

Rules
-----
- NEVER invent employers, dates, metrics, products, or stories the user
  hasn't recorded. Everything concrete must come from fetched data.
- Reference the company name at least twice and at least one specific
  detail from the JD (product area, responsibility phrase, named value,
  team). Show you actually read the posting.
- Length: 300–450 words of body (paragraphs only, not counting header
  block and signature). Don't pad.
- Tone: natural, specific, confident. Active voice. No "synergy",
  "passionate", "dynamic self-starter", "wear many hats".
- If the user's stored history is too thin to support two proof paragraphs,
  collapse to a tighter 3-paragraph structure and flag it in `warning`.
- Use the candidate's preferred_name if available, otherwise legal first
  + last name, otherwise display_name from /auth/me.

Return ONE JSON object, no prose and no markdown fences:

{{
  "title": string,          // e.g. "Cover letter – Acme Senior Engineer"
  "content_md": string,     // the full letter in Markdown, following the layout above
  "warning": string | null  // missing contact info, thin history, etc.
}}
"""


_TAILOR_EMAIL_PROMPT = """You are drafting a short professional email for a
specific job context. The user's full history is behind the same API — pull
what you need.

Environment: $JSP_API_BASE_URL and $JSP_API_TOKEN (bearer). Useful endpoints:

  GET  $JSP_API_BASE_URL/api/v1/history/work
  GET  $JSP_API_BASE_URL/api/v1/history/skills

Email purpose for THIS run: {purpose_label}

Target job
----------
Title:        {title}
Organization: {organization}

Job description (verbatim):

---
{job_description}
---

Existing fit analysis (if any):

{jd_analysis_blob}

User guidance for THIS email (optional):

{extra_notes}

Your job
--------
Write a short, specific email (150–250 words). Include a subject line. No
boilerplate openers. Reference something concrete — a product, a responsibility
phrase, a named person from the user's contacts if applicable, or the stage
they're at in the pipeline. Be warm but brief.

Return ONE JSON object, no prose and no markdown fences:

{{
  "title": string,          // e.g. "Follow-up – Acme Senior Engineer"
  "content_md": string,     // "Subject: ...\\n\\n<body>"
  "warning": string | null
}}
"""


_TAILOR_GENERIC_PROMPT = """You are drafting a document of type `{doc_type}` for
a specific job context. The user's full history is behind the same API — pull
what you need.

Environment: $JSP_API_BASE_URL and $JSP_API_TOKEN (bearer). Useful endpoints:

  GET  $JSP_API_BASE_URL/api/v1/history/work
  GET  $JSP_API_BASE_URL/api/v1/history/skills
  GET  $JSP_API_BASE_URL/api/v1/history/projects
  GET  $JSP_API_BASE_URL/api/v1/history/achievements

Target job
----------
Title:        {title}
Organization: {organization}

Job description (verbatim):

---
{job_description}
---

Existing fit analysis (if any):

{jd_analysis_blob}

User guidance for THIS run (usually tells you exactly what they want — follow it):

{extra_notes}

Your job
--------
Produce a document in Markdown that fits the requested `doc_type`. Use the
user's guidance above as the primary direction; if it's vague, infer a
reasonable default for this doc type in a job-search context. Never invent
experience, companies, or metrics the user has not recorded.

Return ONE JSON object, no prose and no markdown fences:

{{
  "title": string,          // short title for this doc
  "content_md": string,     // the full document markdown
  "notes": string | null,   // brief note on approach / what you emphasized
  "warning": string | null  // caveats (thin history, missing context, etc.)
}}
"""


# Maps writeable doc_type → (prompt_template, purpose_label for emails).
_EMAIL_PURPOSES = {
    "outreach_email": "Cold outreach to a recruiter or hiring manager about this role",
    "thank_you": "Thank-you note after an interview",
    "followup": "Follow-up on a pending application or stalled interview pipeline",
}


def _prompt_for_doc_type(doc_type: str) -> tuple[str, dict]:
    """Return (prompt_template, extra_format_args) for this doc_type."""
    if doc_type == "resume":
        return _TAILOR_RESUME_PROMPT, {}
    if doc_type == "cover_letter":
        return _TAILOR_COVER_LETTER_PROMPT, {}
    if doc_type in _EMAIL_PURPOSES:
        return _TAILOR_EMAIL_PROMPT, {"purpose_label": _EMAIL_PURPOSES[doc_type]}
    # Everything else (portfolio / reference / other / ...) uses the generic prompt.
    return _TAILOR_GENERIC_PROMPT, {"doc_type": doc_type}


async def _run_tailor(
    *,
    db: AsyncSession,
    user: User,
    job: TrackedJob,
    prompt_template: str,
    extra_notes: Optional[str],
    doc_type: str,
    persona_id: Optional[int],
    title_override: Optional[str],
    extra_format_args: Optional[dict] = None,
) -> GeneratedDocument:
    if not (job.job_description and job.job_description.strip()):
        raise HTTPException(
            status_code=422,
            detail="This job has no description stored. Add one before tailoring.",
        )

    org_name = None
    if job.organization_id:
        from app.models.jobs import Organization
        org_row = (
            await db.execute(
                select(Organization.name).where(Organization.id == job.organization_id)
            )
        ).first()
        org_name = org_row[0] if org_row else None

    jd_analysis_blob = (
        json.dumps(job.jd_analysis, indent=2) if job.jd_analysis else "(no analysis yet)"
    )

    # User-supplied values may contain literal `{` / `}` (code blocks,
    # `{foo}` template placeholders, JSON examples inside the JD, etc.).
    # `format_map` interprets those as format-spec syntax and raises on
    # things like `{foo.bar}` or `{0}`. Escape every user value first so the
    # format engine treats their braces as literals.
    def _esc(v: object) -> str:
        return str(v).replace("{", "{{").replace("}", "}}")

    format_kwargs = {
        "title": _esc(job.title or "(untitled)"),
        "organization": _esc(org_name or "(unknown)"),
        "location": _esc(job.location or "(unspecified)"),
        "job_description": _esc(job.job_description),
        "required_skills": _esc(", ".join(job.required_skills or []) or "(none)"),
        "nice_to_have_skills": _esc(", ".join(job.nice_to_have_skills or []) or "(none)"),
        "jd_analysis_blob": _esc(jd_analysis_blob),
        "extra_notes": _esc(extra_notes or "(none)"),
    }
    if extra_format_args:
        for k, v in extra_format_args.items():
            format_kwargs[k] = _esc(v)
    # str.format leaves any unknown placeholders alone-by-raising; since our
    # prompt templates only reference a subset, we use a defaultdict-like dance
    # to tolerate missing keys for the per-template optional placeholders.
    class _SafeDict(dict):
        def __missing__(self, key):
            return "(n/a)"
    prompt = prompt_template.format_map(_SafeDict(**format_kwargs))

    api_token = create_access_token(
        subject=str(user.id), extra={"purpose": f"doc_tailor_{doc_type}"}
    )

    try:
        result = await run_claude_prompt(
            prompt=prompt,
            output_format="json",
            allowed_tools=["Bash"],
            timeout_seconds=240,
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
        )
    except ClaudeCodeError as exc:
        log.warning("Tailor %s failed for job %s: %s", doc_type, job.id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(result.result) or {}
    content_md = (data.get("content_md") or "").strip()
    if not content_md:
        raise HTTPException(
            status_code=502,
            detail="Tailoring returned no content. Check Companion logs.",
        )

    title = (
        title_override
        or data.get("title")
        or f"{doc_type.replace('_', ' ').title()} – {job.title or 'job'}"
    )

    # Version: one more than the highest existing version for this job + doc_type.
    # Also grab the id of that previous version so we can thread parent_version_id.
    prev_row = (
        await db.execute(
            select(GeneratedDocument.id, GeneratedDocument.version)
            .where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.tracked_job_id == job.id,
                GeneratedDocument.doc_type == doc_type,
                GeneratedDocument.deleted_at.is_(None),
            )
            .order_by(GeneratedDocument.version.desc())
            .limit(1)
        )
    ).first()
    next_version = (prev_row[1] + 1) if prev_row else 1
    parent_version_id = prev_row[0] if prev_row else None

    structured = {
        "notes": data.get("notes"),
        "warning": data.get("warning"),
    }

    doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=job.id,
        doc_type=doc_type,
        title=title[:255],
        content_md=content_md,
        content_structured=structured,
        version=next_version,
        parent_version_id=parent_version_id,
        humanized=False,
        persona_id=persona_id,
        source_skill=f"tailor-{doc_type}",
        prompt_snapshot=prompt[:20000],
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.post(
    "/tailor-resume/{job_id:int}",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def tailor_resume(
    job_id: int,
    payload: TailorResumeIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    job = await _get_owned_job(db, job_id, user.id)
    return await _run_tailor(
        db=db,
        user=user,
        job=job,
        prompt_template=_TAILOR_RESUME_PROMPT,
        extra_notes=payload.extra_notes,
        doc_type="resume",
        persona_id=payload.persona_id,
        title_override=payload.title,
    )


@router.post(
    "/tailor-cover-letter/{job_id:int}",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def tailor_cover_letter(
    job_id: int,
    payload: TailorCoverLetterIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    job = await _get_owned_job(db, job_id, user.id)
    return await _run_tailor(
        db=db,
        user=user,
        job=job,
        prompt_template=_TAILOR_COVER_LETTER_PROMPT,
        extra_notes=payload.extra_notes,
        doc_type="cover_letter",
        persona_id=payload.persona_id,
        title_override=payload.title,
    )


class TailorAnyIn(BaseModel):
    doc_type: str = Field(
        description="Target document type. Must be one of DOC_TYPES.",
    )
    extra_notes: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=255)
    persona_id: Optional[int] = None


@router.post(
    "/tailor/{job_id:int}",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def tailor_any(
    job_id: int,
    payload: TailorAnyIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    """Generic tailor endpoint — picks a prompt based on doc_type and runs
    the Companion. Resumes and cover letters use structured prompts;
    outreach/thank-you/followup use an email prompt; everything else uses a
    generic 'draft this kind of document' prompt driven by `extra_notes`.
    """
    if payload.doc_type not in DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown doc_type '{payload.doc_type}'. Allowed: {sorted(DOC_TYPES)}",
        )
    job = await _get_owned_job(db, job_id, user.id)
    prompt_template, extra_args = _prompt_for_doc_type(payload.doc_type)
    return await _run_tailor(
        db=db,
        user=user,
        job=job,
        prompt_template=prompt_template,
        extra_notes=payload.extra_notes,
        doc_type=payload.doc_type,
        persona_id=payload.persona_id,
        title_override=payload.title,
        extra_format_args=extra_args,
    )


# --- Uploads ---------------------------------------------------------------


@router.post(
    "/upload",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    tracked_job_id: Optional[int] = Form(default=None),
    doc_type: str = Form(default="other"),
    title: Optional[str] = Form(default=None),
    source: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    """Save an arbitrary document (PDF, DOCX, image, etc.) as a
    GeneratedDocument row, with the raw bytes on disk.

    Binary and text content are both accepted — for .txt / .md we also
    populate `content_md` so the viewer can render it inline. The original
    file is always preserved and retrievable via GET /documents/{id}/file.

    The Companion can call this endpoint via its service JWT to snapshot
    something it produced (e.g. a PDF rendering of a tailored resume) into
    the user's documents tab.
    """
    if doc_type not in DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown doc_type '{doc_type}'. Allowed: {sorted(DOC_TYPES)}",
        )

    if tracked_job_id is not None:
        await _get_owned_job(db, tracked_job_id, user.id)

    # Read the full body so we can bound size + compute length. FastAPI
    # gives us a SpooledTemporaryFile via UploadFile.
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data)} bytes). Max is {MAX_UPLOAD_BYTES}.",
        )

    original_name = _sanitize_filename(file.filename or "upload")
    # Derive a mime: trust the browser hint if there is one, otherwise guess.
    mime = file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    # Write to /app/uploads/documents/<user_id>/<uuid>_<original>.
    dest_dir = _user_uploads_dir(user.id)
    unique_prefix = uuid.uuid4().hex[:12]
    stored_name = f"{unique_prefix}_{original_name}"
    dest_path = dest_dir / stored_name
    dest_path.write_bytes(data)

    # Extract text content when we can — plain text, PDF, DOCX, HTML all get
    # decoded so the Companion and the in-app editor can work on them.
    # Failures are non-fatal; the original file is always preserved.
    from app.skills.doc_text import extract_text, kind_of

    content_md: Optional[str] = extract_text(data, mime, original_name)
    source_kind = kind_of(mime, original_name)

    effective_title = (title or "").strip() or Path(original_name).stem or "Uploaded document"

    # Version per (user, tracked_job_id, doc_type) — same as tailoring so
    # uploads and generations interleave cleanly on the Documents tab.
    prev_row = (
        await db.execute(
            select(GeneratedDocument.id, GeneratedDocument.version)
            .where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.tracked_job_id == tracked_job_id,
                GeneratedDocument.doc_type == doc_type,
                GeneratedDocument.deleted_at.is_(None),
            )
            .order_by(GeneratedDocument.version.desc())
            .limit(1)
        )
    ).first()
    next_version = (prev_row[1] + 1) if prev_row else 1
    parent_version_id = prev_row[0] if prev_row else None

    # Store file reference in content_structured (no schema migration needed).
    structured = {
        "source": source or "upload",
        "original_filename": original_name,
        "stored_path": str(dest_path.relative_to(UPLOADS_ROOT)),
        "mime_type": mime,
        "size_bytes": len(data),
        "has_inline_text": content_md is not None,
        # What format the content_md was extracted FROM. "text" means the
        # upload was already text-like; "pdf"/"docx"/"html" mean we decoded
        # binary content; "binary" means we couldn't extract anything.
        "extracted_from": source_kind,
    }

    doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=tracked_job_id,
        doc_type=doc_type,
        title=effective_title[:255],
        content_md=content_md,
        content_structured=structured,
        version=next_version,
        parent_version_id=parent_version_id,
        humanized=False,
        source_skill="upload",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{doc_id:int}/file")
async def download_document_file(
    doc_id: int,
    download: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Stream the originally uploaded file (PDF, DOCX, image, etc.).

    Defaults to `Content-Disposition: inline` so that clicking a link opens
    the file in the browser (PDFs render, images display). Append
    `?download=1` to force a download prompt.

    404 if this document was not an upload, or if the backing file has
    gone missing (e.g. the uploads volume was cleared).
    """
    doc = await _get_owned_document(db, doc_id, user.id)
    structured = doc.content_structured or {}
    stored_path = structured.get("stored_path")
    if not stored_path:
        raise HTTPException(
            status_code=404, detail="This document has no uploaded file attached."
        )
    full_path = UPLOADS_ROOT / stored_path
    # Defense in depth: reject anything that escapes UPLOADS_ROOT.
    try:
        full_path.resolve().relative_to(UPLOADS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid file path.")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Backing file not found on disk.")
    mime = structured.get("mime_type") or "application/octet-stream"
    download_name = structured.get("original_filename") or f"document-{doc_id}"
    # Starlette's FileResponse forces attachment disposition when `filename` is
    # set. Override via content_disposition_type so the browser inlines PDFs
    # and images — the root cause of "clicking always downloads".
    return FileResponse(
        path=str(full_path),
        media_type=mime,
        filename=download_name,
        content_disposition_type="attachment" if download else "inline",
    )


# --- Writing Samples Library -----------------------------------------------


class WritingSampleIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content_md: str = Field(min_length=1)
    tags: Optional[list[str]] = None
    source: Optional[str] = None  # e.g. "pasted", "uploaded", "blog", "email"


class WritingSampleOut(WritingSampleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    word_count: Optional[int] = None
    style_signals: Optional[Any] = None
    created_at: datetime
    updated_at: datetime


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


async def _get_owned_sample(
    db: AsyncSession, sample_id: int, user_id: int
) -> WritingSample:
    stmt = select(WritingSample).where(
        WritingSample.id == sample_id,
        WritingSample.user_id == user_id,
        WritingSample.deleted_at.is_(None),
    )
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="Writing sample not found")
    return s


@router.get("/samples", response_model=list[WritingSampleOut])
async def list_samples(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WritingSample]:
    stmt = (
        select(WritingSample)
        .where(
            WritingSample.user_id == user.id,
            WritingSample.deleted_at.is_(None),
        )
        .order_by(WritingSample.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/samples",
    response_model=WritingSampleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_sample(
    payload: WritingSampleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WritingSample:
    s = WritingSample(
        user_id=user.id,
        title=payload.title,
        content_md=payload.content_md,
        tags=payload.tags,
        source=payload.source or "pasted",
        word_count=_word_count(payload.content_md),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@router.put("/samples/{sample_id:int}", response_model=WritingSampleOut)
async def update_sample(
    sample_id: int,
    payload: WritingSampleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WritingSample:
    s = await _get_owned_sample(db, sample_id, user.id)
    s.title = payload.title
    s.content_md = payload.content_md
    s.tags = payload.tags
    s.source = payload.source or s.source
    s.word_count = _word_count(payload.content_md)
    await db.commit()
    await db.refresh(s)
    return s


@router.delete("/samples/{sample_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sample(
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    s = await _get_owned_sample(db, sample_id, user.id)
    s.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


@router.post(
    "/samples/upload",
    response_model=WritingSampleOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_sample(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),  # comma-separated
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WritingSample:
    """Upload a .txt / .md writing sample. Binary formats (.pdf / .docx) are
    accepted but the text extraction is best-effort — if we can't decode the
    bytes as UTF-8 we reject so the user doesn't end up with a garbled
    corpus. If you already have extracted text, use POST /samples with the
    plain body instead."""
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="File too large (max 5 MB for writing samples).",
        )
    try:
        content_md = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422,
            detail=(
                "Couldn't read this file as UTF-8 text. Paste the contents "
                "directly instead, or convert the file to .txt/.md first."
            ),
        )

    tag_list: Optional[list[str]] = None
    if tags and tags.strip():
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    effective_title = (title or "").strip() or Path(
        file.filename or "sample"
    ).stem or "Writing sample"

    s = WritingSample(
        user_id=user.id,
        title=effective_title[:255],
        content_md=content_md,
        tags=tag_list,
        source="uploaded",
        word_count=_word_count(content_md),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


# --- Selection-based editing (used by the Studio editor page) ---------------

_SELECTION_REWRITE_PROMPT = """You are editing a specific span of text in a
larger document. Rewrite ONLY the selected span according to the user's
instruction. Preserve the surrounding voice. Do not summarize or expand
beyond what the instruction asks for.

Document type: {doc_type}
Document title: {title}

User instruction:
{instruction}

Full document for context:

---
{full_body}
---

Selected span (the part you are rewriting):

```
{selection}
```

Return ONE JSON object, no prose, no markdown fences:

{{
  "replacement_text": string,
  "notes": string | null
}}

Rules:
- `replacement_text` must be plain text that drops into the document in place
  of the selection. Preserve markdown syntax if the selection contained any.
- Do NOT include surrounding text that wasn't selected.
- If the instruction is unclear, still produce your best reasonable rewrite.
"""


_SELECTION_ANSWER_PROMPT = """You are answering a question about a specific span
of text in a larger document, WITHOUT modifying the document.

Document type: {doc_type}
Document title: {title}

User question / instruction:
{instruction}

Full document for context:

---
{full_body}
---

Selected span the user is asking about:

```
{selection}
```

Return ONE JSON object, no prose, no markdown fences:

{{
  "answer_text": string,
  "notes": string | null
}}
"""


_SELECTION_NEW_DOC_PROMPT = """You are creating an entirely new document, using
a specific span from a source document as input material or seed.

Source document type: {doc_type}
Source document title: {title}

Target document type for the NEW doc: {new_doc_type}

User instruction:
{instruction}

Source document (for context):

---
{full_body}
---

Selected span from the source (the seed / subject of the new document):

```
{selection}
```

Return ONE JSON object, no prose, no markdown fences:

{{
  "title": string,
  "content_md": string,
  "notes": string | null,
  "warning": string | null
}}

Rules:
- `content_md` is a standalone document — do NOT reference "the selection" or
  "the source document"; incorporate what's needed and stand on its own.
- Fit the `new_doc_type` conventions (resume / cover_letter / outreach_email /
  etc.) where applicable.
"""


class SelectionEditIn(BaseModel):
    mode: str = Field(
        description='One of: "rewrite", "answer", "new_document".',
    )
    selection_text: str = Field(min_length=1)
    selection_start: Optional[int] = None
    selection_end: Optional[int] = None
    instruction: str = Field(min_length=1)
    new_doc_type: Optional[str] = None


class SelectionEditOut(BaseModel):
    mode: str
    replacement_text: Optional[str] = None
    answer_text: Optional[str] = None
    document: Optional[GeneratedDocumentOut] = None
    notes: Optional[str] = None
    warning: Optional[str] = None


@router.post("/{doc_id:int}/selection-edit", response_model=SelectionEditOut)
async def selection_edit(
    doc_id: int,
    payload: SelectionEditIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SelectionEditOut:
    """Run Claude against a selected span with a user instruction.

    Three modes:
      - `rewrite`: proposes replacement text. Does NOT modify the document —
        the UI shows the diff and the user accepts/rejects. Logs a
        `DocumentEdit` row with `accepted=False`.
      - `answer`: returns a prose answer about the span, no document change.
      - `new_document`: creates a brand-new `GeneratedDocument` using the span
        as seed material. Returns the newly created document.
    """
    if payload.mode not in {"rewrite", "answer", "new_document"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown mode '{payload.mode}'. Allowed: rewrite / answer / new_document.",
        )

    doc = await _get_owned_document(db, doc_id, user.id)
    full_body = doc.content_md or ""
    if not full_body.strip():
        raise HTTPException(
            status_code=422,
            detail="This document has no text content to edit against.",
        )

    if payload.mode == "rewrite":
        prompt_template = _SELECTION_REWRITE_PROMPT
    elif payload.mode == "answer":
        prompt_template = _SELECTION_ANSWER_PROMPT
    else:
        prompt_template = _SELECTION_NEW_DOC_PROMPT
        if not payload.new_doc_type:
            raise HTTPException(
                status_code=422, detail="mode='new_document' requires new_doc_type."
            )
        if payload.new_doc_type not in DOC_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown new_doc_type '{payload.new_doc_type}'. Allowed: {sorted(DOC_TYPES)}",
            )

    class _SafeDict(dict):
        def __missing__(self, key):
            return "(n/a)"

    # Escape user values so `{...}` inside a document body doesn't break
    # format_map parsing.
    def _esc(v: object) -> str:
        return str(v).replace("{", "{{").replace("}", "}}")

    prompt = prompt_template.format_map(
        _SafeDict(
            doc_type=_esc(doc.doc_type),
            title=_esc(doc.title),
            instruction=_esc(payload.instruction.strip()),
            full_body=_esc(full_body),
            selection=_esc(payload.selection_text),
            new_doc_type=_esc(payload.new_doc_type or ""),
        )
    )

    try:
        result = await run_claude_prompt(
            prompt=prompt,
            output_format="json",
            allowed_tools=[],
            timeout_seconds=120,
        )
    except ClaudeCodeError as exc:
        log.warning(
            "Selection-edit %s failed for doc %s: %s", payload.mode, doc_id, exc
        )
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(result.result) or {}

    if payload.mode == "rewrite":
        replacement = (data.get("replacement_text") or "").strip()
        if not replacement:
            raise HTTPException(
                status_code=502, detail="Model returned no replacement text."
            )
        edit = DocumentEdit(
            generated_document_id=doc.id,
            editor="companion",
            action="rewrite_selection",
            selection_start=payload.selection_start,
            selection_end=payload.selection_end,
            selection_text=payload.selection_text,
            user_notes=payload.instruction.strip(),
            replacement_text=replacement,
            accepted=False,
        )
        db.add(edit)
        await db.commit()
        return SelectionEditOut(
            mode="rewrite",
            replacement_text=replacement,
            notes=data.get("notes"),
        )

    if payload.mode == "answer":
        answer = (data.get("answer_text") or "").strip()
        if not answer:
            raise HTTPException(status_code=502, detail="Model returned no answer.")
        edit = DocumentEdit(
            generated_document_id=doc.id,
            editor="companion",
            action="answer_question",
            selection_start=payload.selection_start,
            selection_end=payload.selection_end,
            selection_text=payload.selection_text,
            user_notes=payload.instruction.strip(),
            replacement_text=answer,
            accepted=True,
        )
        db.add(edit)
        await db.commit()
        return SelectionEditOut(
            mode="answer", answer_text=answer, notes=data.get("notes")
        )

    # new_document
    content_md = (data.get("content_md") or "").strip()
    if not content_md:
        raise HTTPException(
            status_code=502,
            detail="Model returned no content for the new document.",
        )
    title = data.get("title") or f"From selection of {doc.title}"
    assert payload.new_doc_type is not None

    max_version_row = (
        await db.execute(
            select(GeneratedDocument.version)
            .where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.tracked_job_id == doc.tracked_job_id,
                GeneratedDocument.doc_type == payload.new_doc_type,
                GeneratedDocument.deleted_at.is_(None),
            )
            .order_by(GeneratedDocument.version.desc())
            .limit(1)
        )
    ).first()
    next_version = (max_version_row[0] + 1) if max_version_row else 1

    # For selection-derived new docs the "parent" is the source document the
    # selection came from, even if it's a different doc_type.
    new_doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=doc.tracked_job_id,
        doc_type=payload.new_doc_type,
        title=str(title)[:255],
        content_md=content_md,
        content_structured={
            "notes": data.get("notes"),
            "warning": data.get("warning"),
            "source_doc_id": doc.id,
            "source_selection": payload.selection_text[:500],
            "instruction": payload.instruction.strip()[:500],
        },
        version=next_version,
        parent_version_id=doc.id,
        humanized=False,
        source_skill="selection-new-doc",
        prompt_snapshot=prompt[:20000],
    )
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    return SelectionEditOut(
        mode="new_document",
        document=GeneratedDocumentOut.model_validate(new_doc),
        notes=data.get("notes"),
        warning=data.get("warning"),
    )


# --- Humanizer --------------------------------------------------------------

_HUMANIZE_PROMPT = """You are rewriting a document in the user's own voice,
using their writing samples as the reference corpus for tone, sentence shape,
and word choice. This is NOT a full rewrite — preserve the structure,
headings, bullet content, and factual claims of the source. Change only HOW
things are said.

Source document:
-----
{source_body}
-----

User's writing samples (treat each as an independent example of their
natural voice — mimic cadence and vocabulary, not topic):

{samples_block}

Rules
-----
- NEVER add claims, metrics, companies, or stories not in the source.
- Preserve section structure: if the source is a resume with headings, output
  a resume with the same headings. If it's a cover letter, keep it a cover
  letter.
- Kill AI tells: over-polished parallelism, "moreover", "furthermore", "leveraging",
  empty-phrase openers ("I am excited to…"), triplets-of-adjectives patterns.
- Match the samples' contraction rate, punctuation tics, sentence-length
  distribution, whether they use em-dashes or not, first-person density.
- If a sample contradicts another sample, trust the one that feels closer to
  the source's genre.

Return ONE JSON object, no prose, no markdown fences:

{{
  "content_md": string,
  "notes": string | null,
  "warning": string | null
}}
"""


class HumanizeIn(BaseModel):
    sample_tags: Optional[list[str]] = None
    max_samples: int = Field(default=5, ge=1, le=20)


@router.post(
    "/{doc_id:int}/humanize",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def humanize_document(
    doc_id: int,
    payload: HumanizeIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GeneratedDocument:
    """Rewrite a document in the user's voice using their writing samples.

    Creates a NEW document version (does not mutate the source) with
    `humanized=True`, `parent_version_id` pointing at the source doc, and
    `humanized_from_samples` listing which sample IDs were used.
    """
    source = await _get_owned_document(db, doc_id, user.id)
    if not (source.content_md and source.content_md.strip()):
        raise HTTPException(
            status_code=422,
            detail="Source document has no text to humanize.",
        )

    # Pull writing samples. If the caller asked for a tag filter, match any of
    # the requested tags; otherwise take the most recent N.
    stmt = (
        select(WritingSample)
        .where(
            WritingSample.user_id == user.id,
            WritingSample.deleted_at.is_(None),
        )
        .order_by(WritingSample.created_at.desc())
    )
    samples: list[WritingSample] = list((await db.execute(stmt)).scalars().all())
    if payload.sample_tags:
        wanted = set(payload.sample_tags)
        samples = [
            s for s in samples if set(s.tags or []) & wanted
        ] or samples[: payload.max_samples]
    else:
        samples = samples[: payload.max_samples]

    if not samples:
        raise HTTPException(
            status_code=422,
            detail=(
                "No writing samples on file. Add at least one on the Writing "
                "Samples page before humanizing."
            ),
        )

    def _trim(text: str, cap: int = 2000) -> str:
        return text if len(text) <= cap else text[:cap] + "\n[… truncated …]"

    samples_block_parts: list[str] = []
    for i, s in enumerate(samples, 1):
        tag_str = f" ({', '.join(s.tags)})" if s.tags else ""
        samples_block_parts.append(
            f"--- sample {i}: {s.title}{tag_str} ---\n{_trim(s.content_md)}"
        )
    samples_block = "\n\n".join(samples_block_parts)

    # Escape user content so `{...}` embedded in a document body / writing
    # sample doesn't break format-string parsing.
    def _esc_h(v: object) -> str:
        return str(v).replace("{", "{{").replace("}", "}}")

    prompt = _HUMANIZE_PROMPT.format(
        source_body=_esc_h(source.content_md),
        samples_block=_esc_h(samples_block),
    )

    try:
        result = await run_claude_prompt(
            prompt=prompt,
            output_format="json",
            allowed_tools=[],
            timeout_seconds=180,
        )
    except ClaudeCodeError as exc:
        log.warning("Humanize failed for doc %s: %s", doc_id, exc)
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(result.result) or {}
    content_md = (data.get("content_md") or "").strip()
    if not content_md:
        raise HTTPException(
            status_code=502, detail="Humanizer returned no content."
        )

    # Version per (user, tracked_job_id, doc_type). Humanized output lives in
    # the same stream as the original — it's just another version of the doc.
    max_version_row = (
        await db.execute(
            select(GeneratedDocument.version)
            .where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.tracked_job_id == source.tracked_job_id,
                GeneratedDocument.doc_type == source.doc_type,
                GeneratedDocument.deleted_at.is_(None),
            )
            .order_by(GeneratedDocument.version.desc())
            .limit(1)
        )
    ).first()
    next_version = (max_version_row[0] + 1) if max_version_row else 1

    humanized_doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=source.tracked_job_id,
        doc_type=source.doc_type,
        title=f"{source.title} (humanized)"[:255],
        content_md=content_md,
        content_structured={
            "notes": data.get("notes"),
            "warning": data.get("warning"),
            "humanized_source_doc_id": source.id,
        },
        version=next_version,
        parent_version_id=source.id,
        humanized=True,
        humanized_from_samples=[s.id for s in samples],
        persona_id=source.persona_id,
        source_skill="humanizer",
        prompt_snapshot=prompt[:20000],
    )
    db.add(humanized_doc)
    await db.commit()
    await db.refresh(humanized_doc)
    return humanized_doc
