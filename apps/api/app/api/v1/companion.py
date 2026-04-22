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
  2. Ask the user ONE specific question at a time — don't data-dump.
  3. PUT the entity when they answer.
  4. After each round, summarize what you updated and ask if they want to
     keep going or stop.

Never write without explicit user confirmation in either workflow.

Style: concise, helpful, lightly ironic-corporate in tone. Stay factual.
"""

log = logging.getLogger(__name__)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])


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


@router.post("/conversations/{conv_id}/messages-stream")
async def send_message_stream(
    conv_id: int,
    payload: SendMessageIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the Companion's response as Server-Sent-Events.

    Emits these event shapes:
      {"type":"user_saved","message_id":N}                  — user turn persisted
      {"type":"text_delta","text":"..."}                    — assistant text chunks
      {"type":"tool_use","name":"Bash","input":{...}}       — Companion called a tool
      {"type":"error","message":"..."}                      — something went wrong
      {"type":"done","assistant_message_id":N,
          "conversation_id":N,"cost_usd":0.01,
          "duration_ms":4500,"num_turns":3,
          "skills_inferred":["Bash","WebFetch"]}            — stream complete

    Persists user turn before streaming, assistant turn after streaming.
    """
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

    # Resolve attachments and inline them as a prompt prefix.
    attachments = await _resolve_attached_documents(
        db, user.id, payload.attached_document_ids
    )
    attachments_prefix = _format_attachments_block(attachments)

    # Capture state inside the generator.
    conv_id_local = conv.id
    session_id_in = conv.claude_session_id
    user_msg_id = user_msg.id
    user_content = attachments_prefix + payload.content

    async def event_stream():
        nonlocal session_id_in
        collected_text: list[str] = []
        cost_usd: float | None = None
        duration_ms: int | None = None
        num_turns: int | None = None
        session_id_out: str | None = None
        tool_calls_log: list[dict] = []
        had_error: bool = False
        error_message: str | None = None

        yield _sse({"type": "user_saved", "message_id": user_msg_id})

        # Mirror key events onto the Companion Activity (/queue) live feed so
        # users can see when chat tasks kick off, which tools the Companion
        # used, and when they complete. Tool-use + start + result only — the
        # text deltas stay on the chat page to avoid flooding the activity
        # log with whole essays.
        from app.skills import queue_bus as _bus
        from datetime import datetime as _dt_bus, timezone as _tz_bus

        def _bus_emit(payload: dict) -> None:
            payload = {
                **payload,
                "source": "companion",
                "item_id": f"chat:{conv_id_local}:{user_msg_id}",
                "label": f"Chat: {user_content.strip().splitlines()[0][:80]}" if user_content else "Chat",
                "t": _dt_bus.now(tz=_tz_bus.utc).isoformat(timespec="seconds"),
            }
            _bus.publish(payload)

        _bus_emit({"kind": "start"})

        try:
            async for ev in stream_claude_prompt(
                prompt=user_content,
                session_id=session_id_in,
                system_prompt_append=primer,
                allowed_tools=["Bash", "Read", "Grep", "Glob", "WebFetch", "WebSearch"],
                extra_env={
                    "JSP_API_BASE_URL": "http://localhost:8000",
                    "JSP_API_TOKEN": api_token,
                },
                timeout_seconds=300,
            ):
                ev_type = ev.get("type")

                if ev_type == "error":
                    had_error = True
                    error_message = str(ev.get("message") or "Unknown streaming error")
                    yield _sse({"type": "error", "message": error_message})
                    continue

                if ev_type == "system":
                    sid = ev.get("session_id")
                    if sid:
                        session_id_out = sid
                    continue

                if ev_type == "assistant":
                    # The CLI wraps Messages-API shape in {type:"assistant", message:{...}}.
                    msg = ev.get("message") or {}
                    content_blocks = msg.get("content") or []
                    if isinstance(content_blocks, list):
                        for block in content_blocks:
                            btype = block.get("type")
                            if btype == "text":
                                text = block.get("text") or ""
                                if text:
                                    collected_text.append(text)
                                    yield _sse({"type": "text_delta", "text": text})
                            elif btype == "tool_use":
                                tu = {
                                    "name": block.get("name"),
                                    "id": block.get("id"),
                                    "input": block.get("input"),
                                }
                                tool_calls_log.append(tu)
                                yield _sse({"type": "tool_use", **tu})
                                # Also send a compact version to the activity bus.
                                inp = tu.get("input") or {}
                                compact = {
                                    k: (
                                        (str(v)[:300] + "…")
                                        if isinstance(v, str) and len(str(v)) > 300
                                        else v
                                    )
                                    for k, v in (inp.items() if isinstance(inp, dict) else [])
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
                    # Partial message delta — live token streaming.
                    sub = ev.get("event") or {}
                    sub_type = sub.get("type")
                    if sub_type == "content_block_delta":
                        delta = sub.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            text = delta.get("text") or ""
                            if text:
                                collected_text.append(text)
                                yield _sse({"type": "text_delta", "text": text})
                    continue

                if ev_type == "result":
                    cost_usd = ev.get("total_cost_usd") or ev.get("cost_usd")
                    duration_ms = ev.get("duration_ms")
                    num_turns = ev.get("num_turns")
                    if ev.get("session_id"):
                        session_id_out = ev["session_id"]
                    # Final text is sometimes only present on the result event
                    # (e.g. when partial messages weren't emitted). Use it as a
                    # fallback, but only if we haven't already collected text.
                    if not collected_text and ev.get("result"):
                        txt = str(ev["result"])
                        collected_text.append(txt)
                        yield _sse({"type": "text_delta", "text": txt})
                    _bus_emit(
                        {
                            "kind": "result",
                            "cost_usd": cost_usd,
                            "duration_ms": duration_ms,
                            "num_turns": num_turns,
                        }
                    )
                    continue
        except Exception as exc:  # pragma: no cover
            had_error = True
            error_message = f"Streaming failed: {exc}"
            yield _sse({"type": "error", "message": error_message})
            _bus_emit({"kind": "error", "text": error_message})

        # Publish a terminal "done" to the activity feed so users on /queue
        # see chat tasks reach completion even when they don't have the chat
        # open.
        if not had_error:
            _bus_emit({"kind": "done"})

        # Persist the assistant turn.
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

        # Use a fresh session to persist — the request session may already be
        # closed by the time the generator completes.
        from app.core.database import SessionLocal as _SL

        async with _SL() as db2:
            from app.models.companion import (
                CompanionConversation as _Conv,
                ConversationMessage as _Msg,
            )
            conv_row = (
                await db2.execute(
                    select(_Conv).where(_Conv.id == conv_id_local)
                )
            ).scalar_one_or_none()
            if conv_row is not None and not had_error:
                msg = _Msg(
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
                yield _sse(
                    {
                        "type": "done",
                        "assistant_message_id": msg.id,
                        "conversation_id": conv_row.id,
                        "cost_usd": cost_usd,
                        "duration_ms": duration_ms,
                        "num_turns": num_turns,
                        "skills_inferred": skills_inferred,
                    }
                )
            elif had_error and conv_row is not None:
                # Record error as a system message so it's visible on reload.
                msg = _Msg(
                    conversation_id=conv_row.id,
                    role="system",
                    content_md=error_message or "Streaming error",
                )
                db2.add(msg)
                await db2.commit()
                yield _sse(
                    {
                        "type": "done",
                        "assistant_message_id": None,
                        "conversation_id": conv_row.id,
                        "error": error_message,
                    }
                )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
