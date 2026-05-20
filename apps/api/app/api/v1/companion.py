"""Companion chat — conversations and message exchange via Claude Code CLI."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import create_access_token
from app.models.companion import CompanionConversation, ConversationMessage
from app.models.user import User
from app.schemas.companion import (
    AnalyzeEntityIn,
    ConversationDetail,
    ConversationSummary,
    CreateConversationIn,
    MessageOut,
    SendMessageIn,
    SendMessageOut,
)
from app.skills.runner import ClaudeCodeError, run_claude_prompt

# Compact primer handed to Claude on every Companion turn. It describes the
# entity graph and the read-only API surface. The Companion is expected to
# curl these on demand instead of expecting data pre-injected into the prompt.
_API_PRIMER = """\
You are the Companion for Job Search Pal, helping {display_name} (user id={user_id}).

You are running inside the app's API container and have read access to the
user's own data via HTTP. Use the Bash tool to curl endpoints below when you
need to see what's in the system. Never fabricate history or credentials —
if a field isn't in the data, say so.

Auth:
  • Base URL:   $JSP_API_BASE_URL
  • Bearer:     $JSP_API_TOKEN
  • Add this header to every call:
      curl -H "Authorization: Bearer $JSP_API_TOKEN" $JSP_API_BASE_URL/...

Entity graph (how the pieces fit):

    User
     ├─ WorkExperience ──── organization_id → Organization
     │    └─ Skills (per-role, with usage_notes)
     │
     ├─ Education ────────── organization_id → Organization (university)
     │    └─ Course (many per education)
     │         └─ Skills (per-course, with usage_notes)
     │
     ├─ Skills catalog (canonical, user-scoped)
     │
     ├─ Certification, Project, Publication, Presentation, Achievement,
     │   VolunteerWork, Language, Contact, CustomEvent
     │
     ├─ TrackedJob ──────── organization_id → Organization
     │    ├─ InterviewRound  (ordered; has outcome, notes, rating)
     │    └─ ApplicationEvent (activity feed — status changes, notes)
     │
     └─ EntityLink (polymorphic many-to-many) — use to see how any two
         entities are related. Types: work, education, course, certification,
         project, publication, presentation, achievement, volunteer, language,
         contact, custom, tracked_job, skill.

Key endpoints (all prefixed with /api/v1):

  History
    GET  /history/work                       — list work experiences
    GET  /history/work/{{id}}/skills         — skills linked to that work
    GET  /history/education                  — list education entries
    GET  /history/courses?education_id=N     — courses under an education
    GET  /history/courses/{{id}}/skills      — skills tied to a course
    GET  /history/skills                     — skill catalog
    GET  /history/certifications             — certifications
    GET  /history/projects                   — projects
    GET  /history/publications               — publications
    GET  /history/presentations              — presentations
    GET  /history/achievements               — achievements
    GET  /history/volunteer                  — volunteer work
    GET  /history/languages                  — spoken languages
    GET  /history/contacts                   — networking contacts
    GET  /history/custom-events              — custom dated events
    GET  /history/timeline                   — unified dated feed across all kinds
    GET  /history/links?from_entity_type=X&from_entity_id=Y
                                             — polymorphic links from an entity

  Jobs
    GET  /jobs                               — tracked jobs (?status=X)
    GET  /jobs/{{id}}                        — job detail
    GET  /jobs/{{id}}/rounds                 — interview rounds
    GET  /jobs/{{id}}/artifacts              — take-homes, feedback, offer letters, etc.
    GET  /jobs/{{id}}/events                 — activity feed

  Generated documents (tailored resumes / cover letters / uploads)
    GET  /documents?tracked_job_id=X&doc_type=resume
    GET  /documents/{{id}}                   — full markdown body
    GET  /documents/{{id}}/file              — original uploaded file (PDF, DOCX, etc.)
                                               For uploaded PDFs / DOCX / HTML, the
                                               extracted plain-text is already on the
                                               GeneratedDocument's content_md field, so
                                               GET /documents/{{id}} is usually enough —
                                               you only need /file if you need the
                                               original formatting.
    POST /documents/tailor-resume/{{job_id}} — kick off a tailored resume (slow)
    POST /documents/tailor-cover-letter/{{job_id}}
    POST /documents/tailor/{{job_id}}        — generic tailor; body {{ doc_type, extra_notes,
                                               title?, persona_id? }}. doc_type can be
                                               any DOC_TYPES value (resume, cover_letter,
                                               outreach_email, thank_you, followup, etc.).
    POST /documents/{{id}}/selection-edit    — operate on a specific span of a text
                                               document. body {{ mode, selection_text,
                                               selection_start?, selection_end?, instruction,
                                               new_doc_type? }}. Modes: "rewrite"
                                               (returns replacement_text), "answer" (returns
                                               answer_text, doesn't modify), "new_document"
                                               (creates a new GeneratedDocument from the span).
    POST /documents/upload                   — multipart file upload; binary-safe.
                                               Fields: file (the actual file),
                                               tracked_job_id (optional), doc_type
                                               (resume / cover_letter / offer_letter
                                               / portfolio / reference / other / ...),
                                               title (optional). Use this to stash
                                               PDFs you render, old resumes, offer
                                               letters, etc. into the user's
                                               Documents tab. Example:
                                                 curl -sS -H "Authorization: Bearer $JSP_API_TOKEN" \\
                                                      -F "file=@/tmp/resume.pdf" \\
                                                      -F "doc_type=resume" \\
                                                      -F "title=Rendered resume" \\
                                                      -F "tracked_job_id=123" \\
                                                      "$JSP_API_BASE_URL/api/v1/documents/upload"

  Organizations (employers, schools, cert issuers)
    GET  /organizations?q=search&type=X      — search
    GET  /organizations/{{id}}               — detail
    GET  /organizations/{{id}}/usage         — reference counts
    POST /organizations/{{id}}/research      — enrich via WebSearch/WebFetch;
                                               body {{ hint?: string }}. Fills
                                               website, industry, size, HQ,
                                               description (only if empty),
                                               refreshes research_notes +
                                               reputation_signals, merges
                                               source_links + tech_stack_hints.

Write operations exist for most entities (POST/PUT/DELETE) but do NOT invoke
them unless the user explicitly asks you to modify their data. Always confirm
before writing.

Common workflows
----------------

When the user says "I just applied to X" / "log this job I applied to" /
similar, walk them through ingestion:
  1. Ask for the URL (or title + company if no URL).
  2. If there's a URL, POST /jobs/queue with desired_status=applied and the
     date if they mentioned one — this is cheap, backgrounded, and won't
     block the chat.
  3. Otherwise POST /jobs with the fields they gave you (status=applied).
     After creating, POST /jobs/{{id}}/events with event_type=applied to
     log the ApplicationEvent.
  4. Confirm back to the user what was created with the new job id.

When the user asks to "fill gaps in my history" / "update my profile" /
similar, audit their data:
  1. GET /history/work, /history/education, /history/skills,
     /history/projects, /history/achievements. Flag entries with missing
     highlights, end_date (if not ongoing), role, technologies_used, etc.
  2. PUT the entity when they answer.
  3. After each round, summarize what you updated and ask if they want to
     keep going or stop.

Never write without explicit user confirmation in either workflow.

Diagnostics:
  /app/logs/source_errors.jsonl  — append-only JSONL of every job-source
    poll failure. Each line: {{ts, user_id, source_id, kind, slug_or_url,
    error_class, error_message}}. Use `tail -n 50` or grep by source_id
    when the user asks "why didn't <source> pull anything?". File
    rotates at 5 MB with 3 backups.

Style: concise, helpful, lightly ironic-corporate in tone. Stay factual.
"""

log = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])


# --------------------------------------------------------------------
# In-flight chat run registry
# --------------------------------------------------------------------
# Each in-flight Claude chat lives in `_CHAT_RUNS` keyed by
# "{conv_id}:{user_msg_id}". The background asyncio task owns the
# Claude subprocess and persists the assistant message when it finishes —
# the SSE generator is just a tap that subscribes to a per-run event log,
# so the user can close the chat tab without killing the chat. Late or
# returning clients can re-subscribe and replay the buffered events to
# catch up.
import asyncio as _asyncio_reg
from dataclasses import dataclass, field


@dataclass
class _ChatRun:
    """One in-flight Claude chat turn, decoupled from any HTTP request."""

    task: _asyncio_reg.Task | None = None
    events: list[dict] = field(default_factory=list)  # replay buffer
    subscribers: set[_asyncio_reg.Queue] = field(default_factory=set)
    done: bool = False
    cleanup_handle: _asyncio_reg.TimerHandle | None = None


_CHAT_RUNS: dict[str, _ChatRun] = {}
# How long to keep a finished run around so late subscribers can still
# pick up the terminal "done" / "error" frame and the assistant message id.
_CHAT_RUN_TTL_AFTER_DONE_SECONDS = 60


def _chat_run_key(conv_id: int, user_msg_id: int) -> str:
    return f"{conv_id}:{user_msg_id}"


def _publish_chat_event(run_key: str, ev: dict) -> None:
    """Append `ev` to the run's replay buffer and fan to live subscribers."""
    run = _CHAT_RUNS.get(run_key)
    if run is None:
        return
    run.events.append(ev)
    for q in list(run.subscribers):
        try:
            q.put_nowait(ev)
        except _asyncio_reg.QueueFull:
            # Slow subscriber — drop. They'll still see the replay buffer
            # on reconnect.
            pass


def _schedule_run_cleanup(run_key: str) -> None:
    run = _CHAT_RUNS.get(run_key)
    if run is None:
        return
    if run.cleanup_handle is not None:
        run.cleanup_handle.cancel()
    loop = _asyncio_reg.get_event_loop()
    run.cleanup_handle = loop.call_later(
        _CHAT_RUN_TTL_AFTER_DONE_SECONDS,
        lambda: _CHAT_RUNS.pop(run_key, None),
    )


import re as _re

# Cheap heuristic: scan the assistant's final text for signals that it touched
# specific skills / endpoints / external services. Used to render "Companion
# did X" chips on each turn.
_SKILL_HINT_PATTERNS: list[tuple[str, str]] = [
    (r"/api/v1/jobs/\d+/analyze-jd", "analyze-jd"),
    (r"/api/v1/documents/tailor(?:-resume)?/\d+", "resume-tailor"),
    (r"/api/v1/documents/tailor-cover-letter/\d+", "cover-letter-tailor"),
    (r"/api/v1/documents/tailor/\d+", "tailor"),
    (r"/api/v1/documents/upload", "document-upload"),
    (r"/api/v1/documents/\d+/selection-edit", "selection-edit"),
    (r"/api/v1/organizations/\d+/research", "company-research"),
    (r"/api/v1/jobs/fetch-from-url", "fetch-from-url"),
    (r"/api/v1/jobs/queue", "fetch-queue"),
    (r"\bWebSearch\b", "WebSearch"),
    (r"\bWebFetch\b", "WebFetch"),
    (r"\bcurl\s+-", "curl"),
]


def _infer_skills_used(text: str) -> list[str]:
    if not text:
        return []
    seen: list[str] = []
    for pat, label in _SKILL_HINT_PATTERNS:
        if _re.search(pat, text):
            if label not in seen:
                seen.append(label)
    return seen


async def _get_owned_conversation(
    db: AsyncSession, conv_id: int, user_id: int
) -> CompanionConversation:
    stmt = select(CompanionConversation).where(
        CompanionConversation.id == conv_id,
        CompanionConversation.user_id == user_id,
        CompanionConversation.deleted_at.is_(None),
    )
    conv = (await db.execute(stmt)).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CompanionConversation]:
    stmt = (
        select(CompanionConversation)
        .where(
            CompanionConversation.user_id == user.id,
            CompanionConversation.deleted_at.is_(None),
        )
        .order_by(CompanionConversation.updated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: CreateConversationIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CompanionConversation:
    conv = CompanionConversation(
        user_id=user.id,
        title=payload.title,
        related_tracked_job_id=payload.related_tracked_job_id,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


# ---------------------------------------------------------------------------
# Entity-analysis conversations
# ---------------------------------------------------------------------------

_ANALYZE_ENTITY_MODELS = {
    # entity_type → (SQLAlchemy model, label-attr, link-type-tag)
    # The link-type-tag matches EntityLink.from_entity_type so the
    # Companion can correctly query existing links.
    "work":          ("WorkExperience", "title",   "work"),
    "education":     ("Education",      "degree",  "education"),
    "certification": ("Certification",  "name",    "certification"),
    "publication":   ("Publication",    "title",   "publication"),
    "achievement":   ("Achievement",    "title",   "achievement"),
    "volunteer":     ("VolunteerWork",  "role",    "volunteer"),
    "project":       ("Project",        "name",    "project"),
    "custom":        ("CustomEvent",    "title",   "custom"),
}


async def _load_history_entity(
    db: AsyncSession, user_id: int, entity_type: str, entity_id: int
):
    """Load one history row and return (entity, label, link_tag).
    Raises HTTPException(404) when the row isn't found or isn't owned."""
    if entity_type not in _ANALYZE_ENTITY_MODELS:
        raise HTTPException(status_code=422, detail=f"Unknown entity_type: {entity_type}")
    model_name, label_attr, link_tag = _ANALYZE_ENTITY_MODELS[entity_type]
    from app.models import history as _hmod
    model = getattr(_hmod, model_name)
    stmt = select(model).where(
        model.id == entity_id,
        model.user_id == user_id,
        model.deleted_at.is_(None),
    )
    entity = (await db.execute(stmt)).scalar_one_or_none()
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"{entity_type} #{entity_id} not found",
        )
    label = getattr(entity, label_attr, None) or f"{entity_type} #{entity_id}"
    return entity, label, link_tag


def _format_entity_for_prompt(entity, entity_type: str) -> str:
    """Dump an ORM row's column values to a markdown table-ish block
    Claude can read. Only includes columns with truthy values so the
    Companion focuses on what's present (and notices the gaps)."""
    lines: list[str] = [f"## Current {entity_type} entry"]
    SKIP = {"id", "user_id", "created_at", "updated_at", "deleted_at"}
    table = type(entity).__table__
    for col in table.columns:
        if col.name in SKIP:
            continue
        v = getattr(entity, col.name, None)
        if v in (None, "", [], {}):
            lines.append(f"- {col.name}: *(empty)*")
            continue
        # Truncate huge text columns so the prompt stays reasonable.
        s = str(v)
        if len(s) > 600:
            s = s[:600] + "…"
        lines.append(f"- {col.name}: {s}")
    return "\n".join(lines)


def _build_analyze_seed_prompt(label: str, entity_type: str) -> str:
    """The user-visible message that opens the chat. Short and natural —
    the heavy entity context goes in system_prompt_append instead so
    it doesn't clutter the chat history."""
    return (
        f"Help me build out my {entity_type} entry — **{label}**. "
        "Look at what's there, look at my skills catalog, and start "
        "asking the questions that will make this entry as useful as "
        "possible for job applications. Feel free to suggest concrete "
        "edits — fill in missing fields, link skills, draft a "
        "description, add related projects. Confirm before writing "
        "anything."
    )


def _build_analyze_system_block(
    entity_type: str, entity_label: str, entity_block: str, link_tag: str
) -> str:
    """The system_prompt_append the Companion sees ON TOP of the
    primer. Frames the conversation as an entity-enrichment session
    and tells the agent what's good behavior here."""
    return f"""

Entity-Analysis Mode
====================

This conversation was started by the user clicking "Analyze" on their
**{entity_type}** entry: *{entity_label}*. Treat it as a deep dive — your
job is to enrich this one history record so it pulls weight on the
user's resume and in interviews.

{entity_block}

Working approach (READ THIS — it's the difference between a useful chat
and a "looks fine to me" dud):

  1. Curiosity-first. Ask the user about the specifics behind every
     empty or thin field. Don't accept "I don't remember" as the final
     answer on the first try — offer scaffolding ("which company was
     this for?", "what was the team size?", "what shipped because of
     it?").
  2. Fact-check against existing data. Curl
     GET /api/v1/history/{link_tag}/{{id}}  (when applicable) and
     GET /api/v1/history/skills before claiming something is or isn't
     in their catalog.
  3. Propose concrete edits as the chat progresses. When the user
     gives you a fact, draft the field update (e.g. "I'll write the
     summary as: …") and confirm before PUTting.
  4. Link skills. If the user mentions a tool / language / framework
     they used here, check if it's in their catalog (GET
     /api/v1/history/skills). If yes, link it via the appropriate
     endpoint (see the History section of your primer). If no, ask
     whether they'd like a new Skill row created.
  5. Surface adjacent assets. If the user describes a project that
     came out of this work, suggest creating a Project row and
     linking it via EntityLink (POST /api/v1/history/links). Same for
     achievements, publications, etc.
  6. Tone: lightly curious, lightly ironic-corporate (per the
     Outer-Worlds-aesthetic spec). The user is doing the work; you're
     the diligent assistant making sure no part of this record gets
     phoned in.

Stop conditions: when the user says they're done, or every meaningful
field has either content or an explicit "n/a — couldn't recall".
Summarize what changed at the end so the user knows what to expect on
the entry next time they look at it.
"""


async def _run_analyze_in_background(
    *,
    user_id: int,
    conv_id: int,
    user_display_name: str,
    primer: str,
    user_text: str,
    api_token: str,
) -> None:
    """Spawned by `analyze_entity`. Lives on after the HTTP request
    returns and persists the assistant's first reply (or a `system`
    error message) when Claude finishes. Uses its own session because
    the request-scoped one has already been closed."""
    import asyncio
    from app.core.database import SessionLocal

    try:
        result = await run_claude_prompt(
            prompt=user_text,
            output_format="json",
            session_id=None,
            timeout_seconds=240,
            system_prompt_append=primer,
            allowed_tools=["Bash", "Read", "Grep", "Glob", "WebFetch", "WebSearch"],
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
        )
    except ClaudeCodeError as exc:
        log.warning("analyze-entity background Claude failure: %s", exc)
        async with SessionLocal() as db2:
            db2.add(
                ConversationMessage(
                    conversation_id=conv_id,
                    role="system",
                    content_md=f"Claude Code error starting the analysis: {exc}",
                )
            )
            await db2.commit()
        return
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover
        log.exception("analyze-entity background unhandled error")
        async with SessionLocal() as db2:
            db2.add(
                ConversationMessage(
                    conversation_id=conv_id,
                    role="system",
                    content_md=f"Unexpected error starting the analysis: {type(exc).__name__}: {exc}",
                )
            )
            await db2.commit()
        return

    tool_results_blob = {
        "meta": {
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "num_turns": result.num_turns,
        },
    }
    skills_hinted = _infer_skills_used(result.result)
    if skills_hinted:
        tool_results_blob["skills_inferred"] = skills_hinted

    async with SessionLocal() as db2:
        db2.add(
            ConversationMessage(
                conversation_id=conv_id,
                role="assistant",
                content_md=result.result,
                tool_calls=result.raw.get("tool_use") or result.raw.get("tool_calls"),
                tool_results=tool_results_blob,
            )
        )
        if result.session_id:
            conv = (
                await db2.execute(
                    select(CompanionConversation).where(
                        CompanionConversation.id == conv_id
                    )
                )
            ).scalar_one_or_none()
            if conv is not None:
                conv.claude_session_id = result.session_id
        await db2.commit()


@router.post(
    "/conversations/analyze-entity",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def analyze_entity(
    payload: AnalyzeEntityIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CompanionConversation:
    """Start a fresh Companion conversation focused on enriching one
    history entry. Creates the conversation + the seed user message
    synchronously, then schedules the first Claude turn as a
    background task and returns immediately. The Claude turn is too
    long-running to wait on inside an HTTP handler — Next.js's
    rewrites proxy resets the upstream socket after a minute or so
    and the user sees a 500.

    The /companion page polls the conversation detail and the
    assistant's reply materializes when Claude finishes (typically
    30-90 seconds)."""
    import asyncio

    entity, entity_label, link_tag = await _load_history_entity(
        db, user.id, payload.entity_type, payload.entity_id
    )

    conv = CompanionConversation(
        user_id=user.id,
        title=f"Analyze: {entity_label}"[:255],
    )
    db.add(conv)
    await db.flush()

    user_text = _build_analyze_seed_prompt(entity_label, payload.entity_type)
    entity_block = _format_entity_for_prompt(entity, payload.entity_type)

    # Attach the entity reference to the user message's tool_calls.
    # The frontend reads this on conversation load to decide whether
    # to render the live-entity-detail side panel for this chat.
    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content_md=user_text,
        tool_calls={
            "analyze_seed": {
                "entity_type": payload.entity_type,
                "entity_id": payload.entity_id,
            },
        },
    )
    db.add(user_msg)

    # Ensure the default persona is seeded so the Companion has a tone.
    from app.api.v1.personas import _ensure_default_persona
    await _ensure_default_persona(db, user.id)
    await db.commit()
    await db.refresh(conv)

    primer = _API_PRIMER.format(display_name=user.display_name, user_id=user.id)
    primer += _build_analyze_system_block(
        payload.entity_type, entity_label, entity_block, link_tag
    )
    api_token = create_access_token(
        subject=str(user.id), extra={"purpose": "companion_analyze"}
    )

    # Fire-and-forget: the task lives on after this request returns.
    # We don't keep a reference because we don't need to await it
    # from here. The persister inside the task uses its own session.
    asyncio.create_task(
        _run_analyze_in_background(
            user_id=user.id,
            conv_id=conv.id,
            user_display_name=user.display_name,
            primer=primer,
            user_text=user_text,
            api_token=api_token,
        ),
        name=f"analyze-entity-{conv.id}",
    )

    return conv


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConversationDetail:
    conv = await _get_owned_conversation(db, conv_id, user.id)
    msgs = (
        await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.id.asc())
        )
    ).scalars().all()

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        summary=conv.summary,
        pinned=conv.pinned,
        related_tracked_job_id=conv.related_tracked_job_id,
        claude_session_id=conv.claude_session_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageOut.model_validate(m) for m in msgs],
    )


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    conv = await _get_owned_conversation(db, conv_id, user.id)
    conv.deleted_at = datetime.now(tz=timezone.utc)
    await db.commit()


@router.post("/conversations/{conv_id}/messages", response_model=SendMessageOut)
async def send_message(
    conv_id: int,
    payload: SendMessageIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SendMessageOut:
    conv = await _get_owned_conversation(db, conv_id, user.id)

    # 1. Persist the user turn first so it's in the record even if the LLM
    #    call fails. Also lets the UI optimistically re-render on retry.
    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content_md=payload.content,
        tool_calls=(
            {"attached_document_ids": payload.attached_document_ids}
            if payload.attached_document_ids
            else None
        ),
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    # 2. Build the runtime context handed to Claude for this turn:
    #    - A compact primer describing the API surface (for on-demand curl).
    #    - A short-lived Bearer token scoped to this user so curl can auth.
    #    - Base URL that the subprocess can reach the API at (localhost:8000).
    #    - The user's active Persona, if any, appended as tone / voice guidance.
    api_token = create_access_token(subject=str(user.id), extra={"purpose": "companion"})
    primer = _API_PRIMER.format(display_name=user.display_name, user_id=user.id)

    # Make sure the user has at least the default "Pal" persona seeded so the
    # Companion has a voice to inherit from on first chat.
    from app.api.v1.personas import _ensure_default_persona
    await _ensure_default_persona(db, user.id)
    # Re-read user to pick up active_persona_id set by the seeder.
    await db.refresh(user)

    # Active persona override — read straight from the user row. Kept optional
    # so the Companion still works with no persona configured.
    if user.active_persona_id:
        from app.models.user import Persona as _P
        active = (
            await db.execute(
                select(_P).where(
                    _P.id == user.active_persona_id,
                    _P.user_id == user.id,
                    _P.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            persona_block = [
                "",
                "Active Persona",
                "==============",
                f"Name: {active.name}",
            ]
            if active.description:
                persona_block.append(f"Description: {active.description}")
            if active.tone_descriptors:
                persona_block.append(
                    "Tone: " + ", ".join(str(t) for t in active.tone_descriptors)
                )
            if active.system_prompt and active.system_prompt.strip():
                persona_block.extend(
                    ["", "Custom instructions:", active.system_prompt.strip()]
                )
            primer = primer + "\n" + "\n".join(persona_block) + "\n"

    # Resolve user-attached documents and prefix their content into the
    # prompt so Claude reads them alongside the user's message.
    attachments = await _resolve_attached_documents(
        db, user.id, payload.attached_document_ids
    )
    effective_prompt = payload.content
    if attachments:
        effective_prompt = (
            _format_attachments_block(attachments) + payload.content
        )

    try:
        result = await run_claude_prompt(
            prompt=effective_prompt,
            output_format="json",
            session_id=conv.claude_session_id,
            timeout_seconds=180,
            system_prompt_append=primer,
            # The Companion runs inside an isolated container with a
            # user-scoped bearer token; giving it broad Bash is safe here and
            # lets it compose curl + jq + env without tripping over rule
            # patterns. Read/Grep/Glob let it explore project skills.
            allowed_tools=[
                "Bash",
                "Read",
                "Grep",
                "Glob",
                "WebFetch",
                "WebSearch",
            ],
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
        )
    except ClaudeCodeError as exc:
        log.warning("Claude Code failure for conversation %s: %s", conv.id, exc)
        # Record the failure as a system message so the user sees it in-context
        # without losing the user's turn.
        err_msg = ConversationMessage(
            conversation_id=conv.id,
            role="system",
            content_md=f"Claude Code error: {exc}",
        )
        db.add(err_msg)
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc))

    # 3. Persist the assistant turn and thread the session forward.
    # Cache run metadata (cost / duration / turn count) inside tool_results so
    # the UI can render it on historical messages too — not just the current
    # turn's SendMessageOut response.
    tool_results_blob = {
        "meta": {
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "num_turns": result.num_turns,
        },
        "tool_result_summary": result.raw.get("tool_result_summary"),
    }
    # Inferred skill / endpoint hints from the assistant text. Cheap but useful.
    skills_hinted = _infer_skills_used(result.result)
    if skills_hinted:
        tool_results_blob["skills_inferred"] = skills_hinted

    assistant_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content_md=result.result,
        tool_calls=result.raw.get("tool_use") or result.raw.get("tool_calls"),
        tool_results=tool_results_blob,
    )
    db.add(assistant_msg)

    if result.session_id:
        conv.claude_session_id = result.session_id
    # Derive a title from the first user message if none set yet.
    if not conv.title:
        conv.title = payload.content.strip().splitlines()[0][:80]

    await db.commit()
    await db.refresh(assistant_msg)
    await db.refresh(conv)

    return SendMessageOut(
        user_message=MessageOut.model_validate(user_msg),
        assistant_message=MessageOut.model_validate(assistant_msg),
        conversation=ConversationSummary.model_validate(conv),
        cost_usd=result.cost_usd,
        duration_ms=result.duration_ms,
        num_turns=result.num_turns,
    )


# ---------- Streaming variant ----------------------------------------------

import json as _json_stream

from fastapi.responses import StreamingResponse

from app.skills.runner import stream_claude_prompt


def _sse(event: dict) -> bytes:
    """Format a dict as a Server-Sent-Events data frame."""
    return f"data: {_json_stream.dumps(event)}\n\n".encode("utf-8")


async def _resolve_attached_documents(
    db: AsyncSession, user_id: int, ids: Optional[list[int]]
) -> list:
    """Return GeneratedDocument rows the user attached to a turn.

    Silently drops ids that don't belong to the user (no error — we prefer
    attempting the turn over hard-failing).
    """
    if not ids:
        return []
    from app.models.documents import GeneratedDocument as _GD
    stmt = select(_GD).where(
        _GD.id.in_(ids),
        _GD.user_id == user_id,
        _GD.deleted_at.is_(None),
    )
    rows = list((await db.execute(stmt)).scalars().all())
    # Preserve the user's order.
    by_id = {r.id: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def _format_attachments_block(attachments: list) -> str:
    """Pack attachment bodies into a prompt prefix. Truncates per-file so a
    big upload doesn't blow the context budget on its own."""
    if not attachments:
        return ""
    PER_FILE_CAP = 40_000  # chars
    parts = ["USER ATTACHMENTS", "================"]
    for a in attachments:
        structured = a.content_structured or {}
        extracted_from = structured.get("extracted_from") or "text"
        original = structured.get("original_filename") or a.title
        header = (
            f"--- attachment id={a.id} · {original} "
            f"(doc_type={a.doc_type}, extracted_from={extracted_from}) ---"
        )
        body = a.content_md or ""
        if len(body) > PER_FILE_CAP:
            body = body[:PER_FILE_CAP] + "\n[… truncated for context budget …]"
        if not body.strip():
            body = "(no readable text — binary file preserved at /api/v1/documents/{}/file)".format(a.id)
        parts.append(header)
        parts.append(body)
    parts.append("================")
    parts.append("")
    return "\n\n".join(parts)


async def _build_primer_for(user: User, db: AsyncSession) -> str:
    """Compose the same primer the non-streaming endpoint uses."""
    from app.api.v1.personas import _ensure_default_persona
    await _ensure_default_persona(db, user.id)
    await db.refresh(user)

    primer = _API_PRIMER.format(display_name=user.display_name, user_id=user.id)
    if user.active_persona_id:
        from app.models.user import Persona as _P
        active = (
            await db.execute(
                select(_P).where(
                    _P.id == user.active_persona_id,
                    _P.user_id == user.id,
                    _P.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            persona_block = [
                "",
                "Active Persona",
                "==============",
                f"Name: {active.name}",
            ]
            if active.description:
                persona_block.append(f"Description: {active.description}")
            if active.tone_descriptors:
                persona_block.append(
                    "Tone: " + ", ".join(str(t) for t in active.tone_descriptors)
                )
            if active.system_prompt and active.system_prompt.strip():
                persona_block.extend(
                    ["", "Custom instructions:", active.system_prompt.strip()]
                )
            primer = primer + "\n" + "\n".join(persona_block) + "\n"
    return primer


async def _run_chat_in_background(
    *,
    run_key: str,
    conv_id: int,
    user_msg_id: int,
    session_id_in: str | None,
    user_content: str,
    primer: str,
    api_token: str,
) -> None:
    """Run the Claude stream end-to-end. Owns its own SessionLocal and is
    decoupled from any HTTP request — the chat completes (with the
    assistant message persisted) whether or not anyone is subscribed.

    Events are pushed to the run's replay buffer + live subscribers via
    `_publish_chat_event`. Compact tool/result markers are also published
    onto the Companion Activity (/queue) bus.
    """
    import asyncio as _a
    from app.skills import queue_bus as _bus
    from datetime import datetime as _dt_bus, timezone as _tz_bus
    from app.core.database import SessionLocal as _SL
    from app.skills.runner import stream_claude_prompt as _stream

    _STREAM_TIMEOUT_SECONDS = 900  # 15 min; covers long bulk operations

    collected_text: list[str] = []
    cost_usd: float | None = None
    duration_ms: int | None = None
    num_turns: int | None = None
    session_id_out: str | None = None
    tool_calls_log: list[dict] = []
    had_error: bool = False
    error_message: str | None = None
    persisted_msg_id: int | None = None
    skills_inferred: list[str] = []

    bus_item_id = f"chat:{conv_id}:{user_msg_id}"
    bus_label = (
        f"Chat: {user_content.strip().splitlines()[0][:80]}" if user_content else "Chat"
    )

    def _bus_emit(payload: dict) -> None:
        try:
            _bus.publish(
                {
                    **payload,
                    "source": "companion",
                    "item_id": bus_item_id,
                    "label": bus_label,
                    "t": _dt_bus.now(tz=_tz_bus.utc).isoformat(timespec="seconds"),
                }
            )
        except Exception:
            log.exception("companion stream: bus publish failed")

    _bus_emit({"kind": "start"})
    _publish_chat_event(run_key, {"type": "user_saved", "message_id": user_msg_id})

    try:
        async for ev in _stream(
            prompt=user_content,
            session_id=session_id_in,
            system_prompt_append=primer,
            allowed_tools=["Bash", "Read", "Grep", "Glob", "WebFetch", "WebSearch"],
            extra_env={
                "JSP_API_BASE_URL": "http://localhost:8000",
                "JSP_API_TOKEN": api_token,
            },
            timeout_seconds=_STREAM_TIMEOUT_SECONDS,
        ):
            ev_type = ev.get("type")

            if ev_type == "error":
                had_error = True
                error_message = str(ev.get("message") or "Unknown streaming error")
                _publish_chat_event(
                    run_key, {"type": "error", "message": error_message}
                )
                continue

            if ev_type == "system":
                sid = ev.get("session_id")
                if sid:
                    session_id_out = sid
                continue

            if ev_type == "assistant":
                # CLI wraps Messages-API shape in {type:"assistant", message:{...}}.
                # With --include-partial-messages, text content is ALSO emitted
                # as stream_event content_block_delta below — we only consume
                # tool_use blocks here to avoid doubling every word. Final
                # `result` event has a `result` field used as a fallback when
                # partials are absent entirely.
                msg = ev.get("message") or {}
                content_blocks = msg.get("content") or []
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if block.get("type") == "tool_use":
                            tu = {
                                "name": block.get("name"),
                                "id": block.get("id"),
                                "input": block.get("input"),
                            }
                            tool_calls_log.append(tu)
                            _publish_chat_event(
                                run_key, {"type": "tool_use", **tu}
                            )
                            inp = tu.get("input") or {}
                            compact = {
                                k: (
                                    (str(v)[:300] + "…")
                                    if isinstance(v, str) and len(str(v)) > 300
                                    else v
                                )
                                for k, v in (
                                    inp.items() if isinstance(inp, dict) else []
                                )
                            }
                            _bus_emit(
                                {
                                    "kind": "tool_use",
                                    "tool": tu.get("name"),
                                    "input": compact,
                                }
                            )
                continue

            if ev_type == "stream_event":
                sub = ev.get("event") or {}
                if sub.get("type") == "content_block_delta":
                    delta = sub.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            collected_text.append(text)
                            _publish_chat_event(
                                run_key, {"type": "text_delta", "text": text}
                            )
                continue

            if ev_type == "result":
                cost_usd = ev.get("total_cost_usd") or ev.get("cost_usd")
                duration_ms = ev.get("duration_ms")
                num_turns = ev.get("num_turns")
                if ev.get("session_id"):
                    session_id_out = ev["session_id"]
                if not collected_text and ev.get("result"):
                    txt = str(ev["result"])
                    collected_text.append(txt)
                    _publish_chat_event(
                        run_key, {"type": "text_delta", "text": txt}
                    )
                _bus_emit(
                    {
                        "kind": "result",
                        "cost_usd": cost_usd,
                        "duration_ms": duration_ms,
                        "num_turns": num_turns,
                    }
                )
                continue
    except _a.CancelledError:
        # The chat run task itself was cancelled (e.g. via the Cancel
        # button on /queue). Best-effort persist what we have.
        had_error = True
        error_message = "Chat task cancelled"
    except Exception as exc:  # pragma: no cover
        log.exception("companion stream: producer crashed")
        had_error = True
        error_message = f"Streaming failed: {exc}"

    # Persist the assistant turn — succeeds even if every subscriber dropped.
    try:
        final_text = "".join(collected_text)
        skills_inferred = _infer_skills_used(final_text)
        tool_results_blob = {
            "meta": {
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "num_turns": num_turns,
            },
        }
        if skills_inferred:
            tool_results_blob["skills_inferred"] = skills_inferred

        async with _SL() as db2:
            conv_row = (
                await db2.execute(
                    select(CompanionConversation).where(
                        CompanionConversation.id == conv_id
                    )
                )
            ).scalar_one_or_none()
            if conv_row is not None and not had_error:
                msg = ConversationMessage(
                    conversation_id=conv_row.id,
                    role="assistant",
                    content_md=final_text,
                    tool_calls=tool_calls_log or None,
                    tool_results=tool_results_blob,
                )
                db2.add(msg)
                if session_id_out:
                    conv_row.claude_session_id = session_id_out
                if not conv_row.title:
                    conv_row.title = user_content.strip().splitlines()[0][:80]
                await db2.commit()
                await db2.refresh(msg)
                persisted_msg_id = msg.id
            elif had_error and conv_row is not None:
                if final_text:
                    db2.add(
                        ConversationMessage(
                            conversation_id=conv_row.id,
                            role="assistant",
                            content_md=final_text,
                            tool_calls=tool_calls_log or None,
                            tool_results=tool_results_blob,
                        )
                    )
                db2.add(
                    ConversationMessage(
                        conversation_id=conv_row.id,
                        role="system",
                        content_md=error_message or "Streaming error",
                    )
                )
                if session_id_out:
                    conv_row.claude_session_id = session_id_out
                await db2.commit()
    except Exception:
        log.exception("companion stream: persist failed")

    # Terminal bus + chat events.
    if had_error:
        _bus_emit({"kind": "error", "text": error_message or "Stream ended"})
        _publish_chat_event(
            run_key,
            {
                "type": "done",
                "assistant_message_id": None,
                "conversation_id": conv_id,
                "error": error_message,
            },
        )
    else:
        _bus_emit({"kind": "done"})
        _publish_chat_event(
            run_key,
            {
                "type": "done",
                "assistant_message_id": persisted_msg_id,
                "conversation_id": conv_id,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "num_turns": num_turns,
                "skills_inferred": skills_inferred,
            },
        )

    # Mark the run done and schedule cleanup so late subscribers can still
    # pick up the terminal frames.
    run = _CHAT_RUNS.get(run_key)
    if run is not None:
        run.done = True
    _schedule_run_cleanup(run_key)


@router.post("/conversations/{conv_id}/messages-stream")
async def send_message_stream(
    conv_id: int,
    payload: SendMessageIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the Companion's response as Server-Sent-Events.

    The Claude run is owned by a fire-and-forget background task — the
    SSE response is a thin subscriber on top. If the client closes the
    tab the chat keeps running and the assistant message lands in the
    DB when it finishes. Late or returning clients can reattach via
    the `GET /conversations/{conv_id}/messages/{user_msg_id}/stream`
    endpoint and pick up where they left off via the replay buffer.

    Emits these event shapes:
      {"type":"user_saved","message_id":N}                  — user turn persisted
      {"type":"text_delta","text":"..."}                    — assistant text chunks
      {"type":"tool_use","name":"Bash","input":{...}}       — Companion called a tool
      {"type":"error","message":"..."}                      — something went wrong
      {"type":"done","assistant_message_id":N,
          "conversation_id":N,"cost_usd":0.01,
          "duration_ms":4500,"num_turns":3,
          "skills_inferred":["Bash","WebFetch"]}            — stream complete
    """
    import asyncio as _a

    conv = await _get_owned_conversation(db, conv_id, user.id)

    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content_md=payload.content,
        tool_calls=(
            {"attached_document_ids": payload.attached_document_ids}
            if payload.attached_document_ids
            else None
        ),
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    api_token = create_access_token(subject=str(user.id), extra={"purpose": "companion"})
    primer = await _build_primer_for(user, db)
    attachments = await _resolve_attached_documents(
        db, user.id, payload.attached_document_ids
    )
    attachments_prefix = _format_attachments_block(attachments)

    conv_id_local = conv.id
    session_id_in = conv.claude_session_id
    user_msg_id = user_msg.id
    user_content = attachments_prefix + payload.content
    run_key = _chat_run_key(conv_id_local, user_msg_id)

    # Register the run and kick off the background task. The task lives
    # on after this request returns.
    run = _ChatRun()
    _CHAT_RUNS[run_key] = run
    run.task = _a.create_task(
        _run_chat_in_background(
            run_key=run_key,
            conv_id=conv_id_local,
            user_msg_id=user_msg_id,
            session_id_in=session_id_in,
            user_content=user_content,
            primer=primer,
            api_token=api_token,
        ),
        name=f"chat-stream-{run_key}",
    )

    return StreamingResponse(
        _chat_run_event_stream(run_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations/{conv_id}/messages/{user_msg_id}/stream")
async def reattach_message_stream(
    conv_id: int,
    user_msg_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Re-subscribe to an in-flight chat run. Used by the front-end when
    the user navigates back to a chat whose last message is `user` and
    we want to resume streaming instead of starting a new turn.

    Returns 404 if no run exists for that (conv_id, user_msg_id) — either
    it finished long enough ago to fall out of the registry, or it never
    started. Either way the client should fall back to plain conversation
    polling and read the assistant message from the DB.
    """
    await _get_owned_conversation(db, conv_id, user.id)
    run_key = _chat_run_key(conv_id, user_msg_id)
    if run_key not in _CHAT_RUNS:
        raise HTTPException(status_code=404, detail="No live chat for that message")
    return StreamingResponse(
        _chat_run_event_stream(run_key),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _chat_run_event_stream(run_key: str):
    """SSE generator: replays any buffered events for the run then yields
    live events as they arrive. Detaches cleanly on client disconnect —
    the background run keeps going."""
    import asyncio as _a

    run = _CHAT_RUNS.get(run_key)
    if run is None:
        # Run finished + cleaned up before anyone connected. Tell the
        # client to fall back to polling.
        yield _sse({"type": "error", "message": "Run not found"})
        return

    q: _a.Queue = _a.Queue(maxsize=512)
    run.subscribers.add(q)
    try:
        # Replay any events that arrived before we subscribed so reconnecting
        # clients catch up. New events also arrive on `q` going forward.
        for ev in list(run.events):
            yield _sse(ev)
            if ev.get("type") == "done":
                return

        while True:
            try:
                ev = await _a.wait_for(q.get(), timeout=12.0)
            except _a.TimeoutError:
                # Keepalive comment — proxies and EventSource ignore it.
                yield b": keepalive\n\n"
                continue
            yield _sse(ev)
            if ev.get("type") == "done":
                return
    finally:
        run.subscribers.discard(q)
