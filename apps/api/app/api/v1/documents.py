"""Generated documents: resume tailoring, cover letters, etc.

The "tailor" endpoint kicks off a Claude Code run that pulls the user's
history via the same curl-accessible API used by the Companion, reads the
stored job description, and writes a tailored document back to the
generated_documents table. The document is returned so the UI can show it
immediately.
"""
from __future__ import annotations

import asyncio
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

from app.core.database import SessionLocal, get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.models.documents import DocumentEdit, GeneratedDocument, WritingSample
from app.models.history import (
    Achievement,
    Certification,
    Education,
    Language,
    Project,
    Publication,
    Skill,
    VolunteerWork,
    WorkExperience,
    WorkExperienceSkill,
)
from app.models.jobs import Organization, TrackedJob
from app.models.preferences import Demographics, ResumeProfile, WorkAuthorization
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

_TAILOR_RESUME_PROMPT = """You are TAILORING a resume for a SPECIFIC job posting.

"Tailoring" means: you read the target job carefully, then you pick, reorder,
and rephrase from the candidate's real history to maximize the match for
THIS job. Every section of the output must be informed by THIS job — the
summary, the skills ordering, which roles get the most bullets, which
highlights get surfaced, even which projects you include.

If a role in the history isn't relevant to this job, shrink it to one line.
If a skill isn't relevant, leave it off. If the JD emphasizes something the
candidate has, foreground it. You are not producing a generic resume that
merely happens to be for this company — you are producing THE resume for
THIS posting.

You have two inputs below:

  1. TARGET JOB — the posting you're tailoring for. Read this first.
  2. CANDIDATE PROFILE — everything the app knows about the candidate.
     This is your pool of raw material. Do NOT invent anything outside it.

You do NOT need to make API calls. Everything is pre-fetched. If something
is missing, omit it rather than fabricating.

Prioritize including specific keywords in the job description so that the resume can 
pass automated resume scoring rounds, while not making things up and making the resume
flow without it being obvious it is being keyword optimized.

============================================================
TARGET JOB — this is what you are tailoring FOR
============================================================

{job_context}

Existing JD fit analysis (if present, honour its `resume_emphasis` and
prioritized skills — this was computed specifically for this candidate ×
this JD pairing):

{jd_analysis_blob}

Companion's prior fit summary for this job (if present):

{fit_summary_blob}

User-supplied guidance for THIS tailoring run (highest priority — if set,
these often specify tone, length, or sections to include/exclude):

{extra_notes}

============================================================
CANDIDATE PROFILE — raw material you tailor FROM
============================================================

{candidate_profile}

============================================================

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

Tailoring rules (the important ones — read twice)
--------------------------------------------------
- **Tailor to THIS job, not a generic version.** Before you write each
  section, ask: "does this help the reader see the candidate as a strong
  match for THIS posting?" If not, trim or drop it.
- **Rank ruthlessly by JD fit.** The summary, skill ordering, role order
  within reverse-chronological, which bullets you pick per role, which
  projects (if any) you include — all should reflect what THIS JD asks
  for. A role from 8 years ago that matches the JD can get more bullets
  than last year's role that doesn't.
- **Foreground required skills that the candidate actually has.** Put
  them first in their category. If the JD requires a skill the candidate
  doesn't have, DO NOT add it — just omit silently.

ATS keyword matching (critical — this resume will be scanned by software
before a human sees it)
----------------------------------------------------------------------
Most postings are filtered by an automated screener (ATS) that scores
resumes on exact keyword overlap with the job description. Your job is
to maximize that score **without fabricating anything**:

- **Extract the JD's ATS keywords mentally first.** Look at the verbatim
  JD above for: specific technology names (Kubernetes, Terraform, React,
  Postgres), methodologies (Agile, Scrum, SAFe, OKRs), domain terms
  (HIPAA, PCI-DSS, AML, L4/L7), role-scope verbs ("architected", "led",
  "owned", "shipped"), seniority markers ("senior", "staff", "principal"),
  and exact phrases the JD repeats.
- **Use the JD's exact spelling and casing.** If the JD says
  "PostgreSQL", write PostgreSQL — not "Postgres" or "psql". "TypeScript"
  not "Typescript". "CI/CD" not "CICD". "React.js" not "React" if that's
  what the posting uses. Parsers are literal-string matchers.
- **Mirror JD phrases in bullets.** If the JD says "build scalable
  distributed systems", and a candidate highlight reads "scaled backend
  services to 10M RPS", rephrase as "Built scalable distributed systems
  handling 10M RPS" — the substance is the candidate's real work; the
  wrapper is the JD's vocabulary.
- **Surface every JD-listed skill the candidate truly has.** Do not rely
  on the reader inferring it from context. If the JD lists "Docker",
  "Kubernetes", "Terraform", and the candidate has all three on file,
  every one must appear by name in either Core Skills or a bullet.
- **Cover both spelled-out and acronym forms when the JD uses both.**
  E.g. "Continuous Integration (CI)" or "Search Engine Optimization
  (SEO)" — parsers key on both.
- **Include job-title keywords.** If the JD is for a "Senior Platform
  Engineer" and the candidate's most recent role genuinely matches,
  weave "platform engineering" or "platform" into the summary sentence
  when honest.
- **Avoid images, tables, columns, or text boxes.** Pure markdown only —
  ATS parsers choke on complex layouts. No LaTeX, no graphics.
- **Never keyword-stuff.** Do NOT dump a list of JD terms the candidate
  can't back up. Do NOT invent a skill "just to match the JD". Honest
  keyword overlap beats a scored-well-but-dishonest resume that fails
  the phone screen.

Honesty rules
-------------
- NEVER invent experience, skills, companies, dates, metrics, accomplishments,
  phone numbers, or links. If a field is missing in the candidate profile,
  omit it rather than make one up.
- Rephrase stored highlights into tight, verb-led resume bullets — but do
  not fabricate metrics that aren't in the source.

Formatting rules
----------------
- Target length: one dense page (roughly 450–650 words of markdown body,
  not counting headers). If the candidate's data supports more, lean toward
  1.5 pages for senior candidates; never pad.
- Use consistent date formatting throughout: `Month YYYY – Month YYYY`,
  or `YYYY – YYYY` if only year is on file, or `… – Present` for current.
- Capitalize proper nouns exactly as stored (AWS, PostgreSQL, Kubernetes).
- Never include demographic data (pronouns, age, ethnicity, veteran status)
  on the resume.
- If the candidate's stored data is too thin for a credible resume, set
  `warning` explaining what's missing and produce the honest subset you can.

Return ONE JSON object, no prose, no markdown fences around the JSON:

{{
  "title": string,          // e.g. "Resume – Acme Senior Engineer"
  "content_md": string,     // the full resume in Markdown, following the structure above
  "notes": string,          // 1–2 sentences explicitly naming WHICH aspects of the candidate you surfaced to match THIS JD, and what you trimmed
  "warning": string | null  // honest caveats (missing phone, no dated roles, etc.)
}}
"""


_TAILOR_COVER_LETTER_PROMPT = """You are writing a cover letter TAILORED to a
specific job posting. "Tailored" means: every sentence should be grounded in
THIS job's specifics — the company, the team, the product, the stated
requirements, the stated values — mapped to the candidate's REAL history.

A generic "I'm passionate about software and excited to apply" letter is a
failure. The reader should be unable to swap in a different company name
without the letter falling apart.

You have two inputs below:

  1. TARGET JOB — the posting and organization details. Read this first.
  2. CANDIDATE PROFILE — everything the app knows about the candidate.

You do NOT need to make API calls. Everything is pre-fetched. Never invent
anything outside the profile.

Prioritize including specific keywords in the job description so that the resume can 
pass automated resume scoring rounds, while not making things up and making the resume
flow without it being obvious it is being keyword optimized.

============================================================
TARGET JOB — this is what you are tailoring FOR
============================================================

{job_context}

Existing JD fit analysis (if present, `cover_letter_hook` is especially
useful as your opener — it was computed specifically for this candidate):

{jd_analysis_blob}

Companion's prior fit summary for this job (if present):

{fit_summary_blob}

User guidance for THIS letter (highest priority — tone, length, angle):

{extra_notes}

============================================================
CANDIDATE PROFILE — real history to draw stories from
============================================================

{candidate_profile}

============================================================

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

Tailoring rules (critical)
--------------------------
- **The letter must not be swappable.** If a reader could replace the company
  name with a different one and the letter still works, you've failed. Each
  paragraph should contain at least one detail that's specific to THIS job
  or organization (product, team, stated value, research note, tech stack
  hint, responsibility phrase from the JD).
- Pick proof stories based on JD fit, not recency or prestige. The strongest
  story is the one that most directly answers a specific need in THIS JD.
- Reference the company name at least twice by actual name.
- If the candidate profile includes internal research notes on the org, mine
  them for specificity (why this company specifically — don't just say
  "I admire your mission").
- If the JD mentions a particular product / team / stack, and the candidate
  has relevant stored experience, name both explicitly in the letter.

ATS / keyword guidance
----------------------
Some employers pass cover letters through the same automated screener as
the resume. Without padding or keyword-stuffing:

- Use the JD's exact terminology for technologies and methodologies
  (PostgreSQL, Kubernetes, TypeScript, CI/CD — whatever the posting says,
  with the posting's casing).
- Name 3–5 specific JD-listed skills in context across the paragraphs
  (not as a list — woven into real stories).
- Work in the exact job title the candidate is applying for at least
  once, verbatim from the posting.

Honesty rules
-------------
- NEVER invent employers, dates, metrics, products, or stories the candidate
  hasn't recorded. Everything concrete must come from the candidate profile.
- If the profile is too thin to support two proof paragraphs, collapse to a
  tighter 3-paragraph structure and flag it in `warning`.

Formatting / tone rules
-----------------------
- Length: 300–450 words of body (paragraphs only, not counting header
  block and signature). Don't pad.
- Tone: natural, specific, confident. Active voice. No "synergy",
  "passionate", "dynamic self-starter", "wear many hats".
- Use the candidate's preferred_name if available, otherwise their full
  name as stored in the profile's identity section.

Return ONE JSON object, no prose and no markdown fences:

{{
  "title": string,          // e.g. "Cover letter – Acme Senior Engineer"
  "content_md": string,     // the full letter in Markdown, following the layout above
  "warning": string | null  // missing contact info, thin history, etc.
}}
"""


_TAILOR_EMAIL_PROMPT = """You are drafting a short professional email TAILORED
to a specific job context. Tailored means: the email references something
concrete about THIS company / role / stage — not a generic template.

You have everything you need pre-fetched below.

Email purpose for THIS run: {purpose_label}

============================================================
TARGET JOB — what this email is about
============================================================

{job_context}

Existing JD fit analysis (if any):

{jd_analysis_blob}

User guidance for THIS email:

{extra_notes}

============================================================
CANDIDATE PROFILE — real history to draw from
============================================================

{candidate_profile}

============================================================

Your job
--------
Write a short, specific email (150–250 words) for the purpose named above.
Include a subject line. No boilerplate openers. Reference something concrete
about THIS job / company — a product, a responsibility phrase, a named
person from the user's contacts if applicable, or the stage they're at in
the pipeline. Be warm but brief, and tie at least one sentence back to the
candidate's real history.

Return ONE JSON object, no prose and no markdown fences:

{{
  "title": string,          // e.g. "Follow-up – Acme Senior Engineer"
  "content_md": string,     // "Subject: ...\\n\\n<body>"
  "warning": string | null
}}
"""


_TAILOR_GENERIC_PROMPT = """You are drafting a `{doc_type}` document TAILORED
to a specific job posting. Tailor every section to THIS job — the output
should not work unchanged for a different posting.

You have everything you need pre-fetched below; no API calls required.

============================================================
TARGET JOB — what this document is for
============================================================

{job_context}

Existing JD fit analysis (if any):

{jd_analysis_blob}

User guidance for THIS run (usually tells you exactly what they want — follow it):

{extra_notes}

============================================================
CANDIDATE PROFILE — real history to draw from
============================================================

{candidate_profile}

============================================================

Your job
--------
Produce a document in Markdown that fits the requested `doc_type` and is
TAILORED to the target job above. Use the user's guidance as the primary
direction; if it's vague, infer a reasonable default for this doc type in a
job-search context. Ground every concrete claim in the candidate profile —
never invent experience, companies, or metrics the user hasn't recorded.

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


# ----------------------------------------------------------------------------
# Candidate profile assembler
#
# Builds a single, readable text block the tailor prompt injects so Claude has
# everything it needs at hand — no per-endpoint curl calls required. The block
# is ordered by resume-relevance (identity → summary → skills → experience →
# education → projects → certs/pubs/ach → languages → volunteer). Every
# section is optional; missing data is simply omitted.
# ----------------------------------------------------------------------------


def _fmt_date(d: Optional[Any]) -> Optional[str]:
    if not d:
        return None
    try:
        return d.strftime("%b %Y")
    except Exception:
        return str(d)


def _fmt_date_range(
    start: Optional[Any], end: Optional[Any], *, ongoing_label: str = "Present"
) -> Optional[str]:
    s = _fmt_date(start)
    e = _fmt_date(end) or (ongoing_label if start else None)
    if s and e:
        return f"{s} – {e}"
    return s or e


def _fmt_list(items: Optional[list]) -> Optional[str]:
    if not items:
        return None
    return ", ".join(str(x) for x in items if str(x).strip())


async def _build_candidate_profile_block(
    db: AsyncSession, user: User
) -> str:
    """Assemble a Markdown block covering every stored entity that could
    plausibly appear on a tailored resume or cover letter.
    """

    # --- 1. Identity & contact ---------------------------------------------
    rp = (
        await db.execute(
            select(ResumeProfile).where(
                ResumeProfile.user_id == user.id,
                ResumeProfile.deleted_at.is_(None),
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
    wa = (
        await db.execute(
            select(WorkAuthorization).where(
                WorkAuthorization.user_id == user.id,
                WorkAuthorization.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    # Resolve the canonical display name:
    #   resume_profile.full_name > preferred_name > legal_first + legal_last
    #   > display_name > email local-part
    name = None
    if rp and rp.full_name:
        name = rp.full_name.strip()
    elif demo and demo.preferred_name:
        name = demo.preferred_name.strip()
        if demo.legal_last_name:
            name = f"{name} {demo.legal_last_name.strip()}"
    elif demo and (demo.legal_first_name or demo.legal_last_name):
        parts = [demo.legal_first_name, demo.legal_middle_name, demo.legal_last_name]
        name = " ".join(p.strip() for p in parts if p and p.strip())
    elif user.display_name:
        name = user.display_name.strip()

    email = (rp.email if rp and rp.email else user.email) or None
    phone = rp.phone if rp and rp.phone else None
    location = None
    if rp and rp.location:
        location = rp.location.strip()
    elif wa and (wa.current_location_city or wa.current_location_region):
        loc_parts = [wa.current_location_city, wa.current_location_region]
        location = ", ".join(p.strip() for p in loc_parts if p and p.strip()) or None

    links: list[tuple[str, str]] = []
    if rp:
        if rp.linkedin_url: links.append(("LinkedIn", rp.linkedin_url))
        if rp.github_url: links.append(("GitHub", rp.github_url))
        if rp.portfolio_url: links.append(("Portfolio", rp.portfolio_url))
        if rp.website_url: links.append(("Website", rp.website_url))
        for extra in (rp.other_links or []):
            if isinstance(extra, dict) and extra.get("label") and extra.get("url"):
                links.append((str(extra["label"]), str(extra["url"])))

    out: list[str] = []
    out.append("## Identity & contact")
    out.append(f"- Full name: {name or '(not set)'}")
    if rp and rp.headline:
        out.append(f"- Headline / title: {rp.headline}")
    out.append(f"- Email: {email or '(not set)'}")
    if phone: out.append(f"- Phone: {phone}")
    if location: out.append(f"- Location: {location}")
    for label, url in links:
        out.append(f"- {label}: {url}")
    if demo and demo.preferred_name:
        out.append(f"- Preferred name (for salutation): {demo.preferred_name}")
    if rp and rp.professional_summary:
        out.append("")
        out.append("### User-authored default summary (use as a seed; rephrase for this JD)")
        out.append(rp.professional_summary.strip())

    # --- 2. Skills (pulled first, both as a catalog and to annotate jobs) ---
    skills_rows = (
        await db.execute(
            select(Skill).where(
                Skill.user_id == user.id,
                Skill.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    skill_by_id = {s.id: s for s in skills_rows}

    if skills_rows:
        by_cat: dict[str, list[Skill]] = {}
        for s in skills_rows:
            by_cat.setdefault(s.category or "general", []).append(s)
        out.append("")
        out.append("## Skills catalog")
        out.append(
            "(Every skill the user has on file. Only include the ones actually "
            "relevant to this JD in the final resume — this list is your source of truth.)"
        )
        for cat in sorted(by_cat.keys()):
            out.append(f"### {cat}")
            for s in sorted(by_cat[cat], key=lambda x: x.name.lower()):
                bits = [s.name]
                if s.proficiency:
                    bits.append(f"proficiency: {s.proficiency}")
                if s.years_experience is not None:
                    bits.append(f"{float(s.years_experience):g} yrs")
                last = _fmt_date(s.last_used_date)
                if last:
                    bits.append(f"last used {last}")
                aliases = s.aliases or []
                if aliases:
                    bits.append("aka " + ", ".join(str(a) for a in aliases))
                out.append(f"- {' · '.join(bits)}")

    # --- 3. Work experience + linked skills --------------------------------
    work_rows = (
        await db.execute(
            select(WorkExperience).where(
                WorkExperience.user_id == user.id,
                WorkExperience.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    work_rows.sort(
        key=lambda w: (w.end_date or w.start_date or __import__("datetime").date.min),
        reverse=True,
    )

    work_skill_rows = (
        await db.execute(
            select(WorkExperienceSkill).where(
                WorkExperienceSkill.work_experience_id.in_(
                    [w.id for w in work_rows] or [0]
                )
            )
        )
    ).scalars().all()
    skills_by_work: dict[int, list[tuple[str, Optional[str]]]] = {}
    for link in work_skill_rows:
        s = skill_by_id.get(link.skill_id)
        if not s:
            continue
        skills_by_work.setdefault(link.work_experience_id, []).append(
            (s.name, link.usage_notes)
        )

    org_ids: set[int] = set()
    for w in work_rows:
        if w.organization_id: org_ids.add(w.organization_id)

    # --- 4. Education ------------------------------------------------------
    edu_rows = (
        await db.execute(
            select(Education).where(
                Education.user_id == user.id,
                Education.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    edu_rows.sort(
        key=lambda e: (e.end_date or e.start_date or __import__("datetime").date.min),
        reverse=True,
    )
    for e in edu_rows:
        if e.organization_id: org_ids.add(e.organization_id)

    # --- 5. Fetch all referenced orgs in one query -------------------------
    org_by_id: dict[int, Organization] = {}
    if org_ids:
        rows = (
            await db.execute(
                select(Organization).where(Organization.id.in_(org_ids))
            )
        ).scalars().all()
        org_by_id = {o.id: o for o in rows}

    def _org_name(oid: Optional[int]) -> Optional[str]:
        if not oid: return None
        o = org_by_id.get(oid)
        return o.name if o else None

    if work_rows:
        out.append("")
        out.append("## Work experience (most recent first)")
        for w in work_rows:
            header = w.title or "(untitled role)"
            org = _org_name(w.organization_id)
            if org: header += f" — {org}"
            out.append(f"### {header}")
            meta_bits = []
            rng = _fmt_date_range(w.start_date, w.end_date)
            if rng: meta_bits.append(rng)
            if w.location: meta_bits.append(w.location)
            if w.employment_type: meta_bits.append(w.employment_type)
            if w.remote_policy: meta_bits.append(w.remote_policy)
            if w.team_size: meta_bits.append(f"team of {w.team_size}")
            if meta_bits:
                out.append("*" + " · ".join(meta_bits) + "*")
            if w.summary:
                out.append(w.summary.strip())
            if w.highlights:
                out.append("Highlights:")
                for h in w.highlights:
                    out.append(f"- {h}")
            tech = _fmt_list(w.technologies_used)
            if tech: out.append(f"Technologies used: {tech}")
            linked = skills_by_work.get(w.id) or []
            if linked:
                parts = []
                for sname, notes in linked:
                    parts.append(f"{sname}" + (f" ({notes})" if notes else ""))
                out.append(f"Linked skills: {', '.join(parts)}")
            if w.manager_name:
                out.append(f"Manager: {w.manager_name}")

    # --- 6. Education body -------------------------------------------------
    if edu_rows:
        out.append("")
        out.append("## Education (most recent first)")
        for e in edu_rows:
            degree = e.degree or "(degree)"
            field = e.field_of_study
            header = degree
            if field: header += f", {field}"
            org = _org_name(e.organization_id)
            if org: header += f" — {org}"
            out.append(f"### {header}")
            meta_bits = []
            rng = _fmt_date_range(e.start_date, e.end_date, ongoing_label="Expected")
            if rng: meta_bits.append(rng)
            if e.concentration: meta_bits.append(f"concentration: {e.concentration}")
            if e.minor: meta_bits.append(f"minor: {e.minor}")
            if e.gpa is not None: meta_bits.append(f"GPA {float(e.gpa):.2f}")
            if meta_bits:
                out.append("*" + " · ".join(meta_bits) + "*")
            honors = _fmt_list(e.honors)
            if honors: out.append(f"Honors: {honors}")
            if e.thesis_title:
                out.append(f"Thesis: {e.thesis_title}")
            if e.notes:
                out.append(e.notes.strip())

    # --- 7. Projects -------------------------------------------------------
    projects = (
        await db.execute(
            select(Project).where(
                Project.user_id == user.id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    projects.sort(
        key=lambda p: (p.end_date or p.start_date or __import__("datetime").date.min),
        reverse=True,
    )
    if projects:
        out.append("")
        out.append("## Projects")
        for p in projects:
            header = p.name
            if p.role: header += f" — {p.role}"
            out.append(f"### {header}")
            meta_bits = []
            rng = _fmt_date_range(p.start_date, p.end_date)
            if rng: meta_bits.append(rng)
            elif p.is_ongoing: meta_bits.append("ongoing")
            if p.url: meta_bits.append(p.url)
            if p.repo_url: meta_bits.append(p.repo_url)
            if meta_bits:
                out.append("*" + " · ".join(meta_bits) + "*")
            if p.summary: out.append(p.summary.strip())
            if p.highlights:
                for h in p.highlights:
                    out.append(f"- {h}")
            tech = _fmt_list(p.technologies_used)
            if tech: out.append(f"Technologies: {tech}")

    # --- 8. Certifications -------------------------------------------------
    certs = (
        await db.execute(
            select(Certification).where(
                Certification.user_id == user.id,
                Certification.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    certs.sort(
        key=lambda c: (c.issued_date or __import__("datetime").date.min), reverse=True
    )
    if certs:
        out.append("")
        out.append("## Certifications")
        for c in certs:
            line = c.name
            if c.issuer: line += f" — {c.issuer}"
            issued = _fmt_date(c.issued_date)
            if issued: line += f" · issued {issued}"
            expires = _fmt_date(c.expires_date)
            if expires: line += f" · expires {expires}"
            if c.credential_url: line += f" · {c.credential_url}"
            out.append(f"- {line}")

    # --- 9. Publications ---------------------------------------------------
    pubs = (
        await db.execute(
            select(Publication).where(
                Publication.user_id == user.id,
                Publication.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    pubs.sort(
        key=lambda p: (p.publication_date or __import__("datetime").date.min),
        reverse=True,
    )
    if pubs:
        out.append("")
        out.append("## Publications")
        for p in pubs:
            line = p.title
            if p.venue: line += f" — {p.venue}"
            d = _fmt_date(p.publication_date)
            if d: line += f" · {d}"
            if p.url: line += f" · {p.url}"
            out.append(f"- {line}")

    # --- 10. Achievements --------------------------------------------------
    achs = (
        await db.execute(
            select(Achievement).where(
                Achievement.user_id == user.id,
                Achievement.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    achs.sort(
        key=lambda a: (a.date_awarded or __import__("datetime").date.min), reverse=True
    )
    if achs:
        out.append("")
        out.append("## Achievements")
        for a in achs:
            line = a.title
            if a.issuer: line += f" — {a.issuer}"
            d = _fmt_date(a.date_awarded)
            if d: line += f" · {d}"
            out.append(f"- {line}")
            if a.description:
                out.append(f"  {a.description.strip()}")

    # --- 11. Languages -----------------------------------------------------
    langs = (
        await db.execute(
            select(Language).where(
                Language.user_id == user.id,
                Language.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if langs:
        out.append("")
        out.append("## Languages")
        for lg in langs:
            line = lg.name
            if lg.proficiency: line += f" ({lg.proficiency})"
            out.append(f"- {line}")

    # --- 12. Volunteer work ------------------------------------------------
    vols = (
        await db.execute(
            select(VolunteerWork).where(
                VolunteerWork.user_id == user.id,
                VolunteerWork.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    vols.sort(
        key=lambda v: (v.end_date or v.start_date or __import__("datetime").date.min),
        reverse=True,
    )
    if vols:
        out.append("")
        out.append("## Volunteer")
        for v in vols:
            header = v.organization
            if v.role: header += f" — {v.role}"
            out.append(f"### {header}")
            meta_bits = []
            rng = _fmt_date_range(v.start_date, v.end_date)
            if rng: meta_bits.append(rng)
            if v.cause_area: meta_bits.append(v.cause_area)
            if v.hours_total: meta_bits.append(f"{v.hours_total}h total")
            if meta_bits:
                out.append("*" + " · ".join(meta_bits) + "*")
            if v.summary: out.append(v.summary.strip())
            if v.highlights:
                for h in v.highlights:
                    out.append(f"- {h}")

    if len(out) <= 6:
        # Only identity was populated — everything else is empty. Flag it so
        # Claude knows to set a `warning` rather than fabricate.
        out.append("")
        out.append(
            "_(No history entries on file yet — user must populate work, education, "
            "or skills before a credible resume can be produced.)_"
        )

    return "\n".join(out)


def _build_job_context_block(
    job: TrackedJob, org: Optional[Organization]
) -> str:
    """Assemble a readable block covering everything we know about the target
    job + employer. The resume/cover-letter prompts tailor TO this block.
    """
    out: list[str] = []
    out.append("## Role")
    out.append(f"- Title: {job.title or '(untitled)'}")
    out.append(f"- Organization: {org.name if org else '(unknown)'}")
    if job.location: out.append(f"- Location: {job.location}")
    if job.remote_policy: out.append(f"- Remote policy: {job.remote_policy}")
    if job.employment_type: out.append(f"- Employment type: {job.employment_type}")
    if job.experience_level: out.append(f"- Seniority: {job.experience_level}")
    if job.experience_years_min is not None or job.experience_years_max is not None:
        lo = job.experience_years_min
        hi = job.experience_years_max
        if lo is not None and hi is not None:
            rng = f"{lo}–{hi} yrs"
        elif lo is not None:
            rng = f"{lo}+ yrs"
        else:
            rng = f"up to {hi} yrs"
        out.append(f"- Experience required: {rng}")
    if job.education_required:
        out.append(f"- Education required: {job.education_required}")
    if job.salary_min or job.salary_max:
        cur = job.salary_currency or "USD"
        bits = []
        if job.salary_min: bits.append(f"min {cur} {float(job.salary_min):,.0f}")
        if job.salary_max: bits.append(f"max {cur} {float(job.salary_max):,.0f}")
        out.append(f"- Salary: {' · '.join(bits)}")
    if job.visa_sponsorship_offered is not None:
        out.append(f"- Visa sponsorship offered: {'yes' if job.visa_sponsorship_offered else 'no'}")
    if job.relocation_offered is not None:
        out.append(f"- Relocation offered: {'yes' if job.relocation_offered else 'no'}")
    if job.source_url:
        out.append(f"- Source URL: {job.source_url}")
    if job.source_platform:
        out.append(f"- Source platform: {job.source_platform}")
    if job.date_posted:
        out.append(f"- Date posted: {_fmt_date(job.date_posted)}")

    if job.required_skills:
        out.append("")
        out.append("## Required skills (from the JD)")
        out.append(", ".join(str(s) for s in job.required_skills))
    if job.nice_to_have_skills:
        out.append("")
        out.append("## Nice-to-have skills (from the JD)")
        out.append(", ".join(str(s) for s in job.nice_to_have_skills))

    if org:
        org_bits: list[str] = []
        if org.industry: org_bits.append(f"industry: {org.industry}")
        if org.size: org_bits.append(f"size: {org.size}")
        if org.headquarters_location: org_bits.append(f"HQ: {org.headquarters_location}")
        if org.website: org_bits.append(f"website: {org.website}")
        if org_bits or org.description or org.research_notes or org.tech_stack_hints:
            out.append("")
            out.append(f"## About the organization — {org.name}")
            if org_bits:
                out.append(" · ".join(org_bits))
            if org.description:
                out.append("")
                out.append("Description:")
                out.append(org.description.strip())
            if org.research_notes:
                out.append("")
                out.append("Internal research notes (useful for cover letter specificity):")
                out.append(org.research_notes.strip())
            if org.tech_stack_hints:
                out.append("")
                out.append(
                    "Tech stack hints: "
                    + ", ".join(str(t) for t in org.tech_stack_hints)
                )

    if job.notes:
        out.append("")
        out.append("## User's private notes on this job")
        out.append(
            "(Weight these — they often contain context the JD doesn't capture.)"
        )
        out.append(job.notes.strip())

    out.append("")
    out.append("## Job description (verbatim)")
    out.append("---")
    out.append((job.job_description or "").strip())
    out.append("---")

    return "\n".join(out)


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

    org: Optional[Organization] = None
    if job.organization_id:
        org = (
            await db.execute(
                select(Organization).where(Organization.id == job.organization_id)
            )
        ).scalar_one_or_none()
    org_name = org.name if org else None

    jd_analysis_blob = (
        json.dumps(job.jd_analysis, indent=2) if job.jd_analysis else "(no analysis yet)"
    )
    fit_summary_blob = (
        json.dumps(job.fit_summary, indent=2) if job.fit_summary else "(none)"
    )

    candidate_profile = await _build_candidate_profile_block(db, user)
    job_context = _build_job_context_block(job, org)

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
        "fit_summary_blob": _esc(fit_summary_blob),
        "extra_notes": _esc(extra_notes or "(none)"),
        "candidate_profile": _esc(candidate_profile),
        "job_context": _esc(job_context),
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

    # Version: one more than the highest existing version for this job + doc_type.
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

    title = (
        title_override
        or f"{doc_type.replace('_', ' ').title()} – {job.title or 'job'}"
    )

    # Create the placeholder row synchronously. The background task fills in
    # content_md + structured when Claude returns. This keeps the HTTP request
    # short (< 1s) so the Next.js proxy doesn't time out — Claude runs can
    # take several minutes.
    doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=job.id,
        doc_type=doc_type,
        title=title[:255],
        content_md=None,
        content_structured={
            "status": "generating",
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": None,
            "warning": None,
            "error": None,
        },
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

    # Kick off the long-running Claude call outside the request scope. We use
    # asyncio.create_task so the request returns immediately; the task owns
    # its own DB session via SessionLocal.
    asyncio.create_task(
        _finish_tailor_in_background(
            doc_id=doc.id,
            prompt=prompt,
            doc_type=doc_type,
            title_override=title_override,
            job_title=job.title or "job",
            api_token=api_token,
        ),
        name=f"tailor-{doc_type}-{doc.id}",
    )
    return doc


async def _finish_tailor_in_background(
    *,
    doc_id: int,
    prompt: str,
    doc_type: str,
    title_override: Optional[str],
    job_title: str,
    api_token: str,
) -> None:
    """Run Claude in the background, then update the placeholder doc row with
    the result. Runs with its own DB session because the request scope is gone.
    Streams live events onto the queue_bus so /queue can narrate progress."""
    from app.skills.queue_bus import run_claude_to_bus

    label = f"{doc_type.replace('_', ' ').title()}: {job_title}"
    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source=f"tailor_{doc_type}",
            item_id=f"doc:{doc_id}",
            label=label,
            allowed_tools=["Bash"],
            timeout_seconds=600,
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
        )
    except ClaudeCodeError as exc:
        log.warning("Tailor %s failed (doc %s): %s", doc_type, doc_id, exc)
        await _mark_tailor_error(doc_id, f"Claude Code error: {exc}")
        return
    except Exception as exc:  # defensive — task must not crash silently
        log.exception("Tailor %s crashed (doc %s)", doc_type, doc_id)
        await _mark_tailor_error(doc_id, f"Unexpected error: {exc}")
        return

    data = _extract_json_object(final_text) or {}
    content_md = (data.get("content_md") or "").strip()
    if not content_md:
        await _mark_tailor_error(
            doc_id, "Tailoring returned no content. Check Companion logs."
        )
        return

    title = (
        title_override
        or data.get("title")
        or f"{doc_type.replace('_', ' ').title()} – {job_title}"
    )

    async with SessionLocal() as db:
        doc = (
            await db.execute(
                select(GeneratedDocument).where(GeneratedDocument.id == doc_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            log.warning("Tailor background: doc %s vanished before save", doc_id)
            return
        doc.content_md = content_md
        doc.title = title[:255]
        doc.content_structured = {
            "status": "ready",
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": data.get("notes"),
            "warning": data.get("warning"),
            "error": None,
        }
        await db.commit()


async def _mark_tailor_error(doc_id: int, message: str) -> None:
    """Update the placeholder doc row with an error status so the UI can show it."""
    try:
        async with SessionLocal() as db:
            doc = (
                await db.execute(
                    select(GeneratedDocument).where(GeneratedDocument.id == doc_id)
                )
            ).scalar_one_or_none()
            if doc is None:
                return
            doc.content_structured = {
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "notes": None,
                "warning": None,
                "error": message,
            }
            await db.commit()
    except Exception:
        log.exception("Failed to record tailor error for doc %s", doc_id)


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

    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source=f"selection_{payload.mode}",
            item_id=f"doc:{doc.id}:edit:{int(datetime.now(timezone.utc).timestamp())}",
            label=f"{payload.mode.replace('_', ' ').title()}: {doc.title}",
            allowed_tools=[],
            timeout_seconds=120,
        )
    except ClaudeCodeError as exc:
        log.warning(
            "Selection-edit %s failed for doc %s: %s", payload.mode, doc_id, exc
        )
        raise HTTPException(status_code=502, detail=f"Claude Code error: {exc}")

    data = _extract_json_object(final_text) or {}

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

    # Create the placeholder row synchronously, then kick Claude into a
    # background task so the HTTP request returns quickly. The /studio page
    # polls the doc until status flips to "ready" or "error".
    humanized_doc = GeneratedDocument(
        user_id=user.id,
        tracked_job_id=source.tracked_job_id,
        doc_type=source.doc_type,
        title=f"{source.title} (humanized)"[:255],
        content_md=None,
        content_structured={
            "status": "generating",
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "humanized_source_doc_id": source.id,
            "notes": None,
            "warning": None,
            "error": None,
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

    asyncio.create_task(
        _finish_humanize_in_background(
            doc_id=humanized_doc.id,
            prompt=prompt,
            source_doc_id=source.id,
            source_title=source.title,
        ),
        name=f"humanize-{humanized_doc.id}",
    )
    return humanized_doc


async def _finish_humanize_in_background(
    *,
    doc_id: int,
    prompt: str,
    source_doc_id: int,
    source_title: str,
) -> None:
    """Mirror of _finish_tailor_in_background for the humanizer."""
    from app.skills.queue_bus import run_claude_to_bus

    try:
        final_text = await run_claude_to_bus(
            prompt=prompt,
            source="humanize",
            item_id=f"doc:{doc_id}",
            label=f"Humanize: {source_title}",
            allowed_tools=[],
            timeout_seconds=600,
        )
    except ClaudeCodeError as exc:
        log.warning("Humanize failed (doc %s): %s", doc_id, exc)
        await _mark_tailor_error(doc_id, f"Claude Code error: {exc}")
        return
    except Exception as exc:
        log.exception("Humanize crashed (doc %s)", doc_id)
        await _mark_tailor_error(doc_id, f"Unexpected error: {exc}")
        return

    data = _extract_json_object(final_text) or {}
    content_md = (data.get("content_md") or "").strip()
    if not content_md:
        await _mark_tailor_error(doc_id, "Humanizer returned no content.")
        return

    async with SessionLocal() as db:
        doc = (
            await db.execute(
                select(GeneratedDocument).where(GeneratedDocument.id == doc_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            return
        doc.content_md = content_md
        doc.content_structured = {
            "status": "ready",
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "humanized_source_doc_id": source_doc_id,
            "notes": data.get("notes"),
            "warning": data.get("warning"),
            "error": None,
        }
        await db.commit()
