"""Companion chat — conversations and message exchange via Claude Code CLI."""

import json
import logging
from datetime import datetime, timezone

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

Style: concise, helpful, lightly ironic-corporate in tone. Stay factual.
"""

log = logging.getLogger(__name__)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])


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
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    # 2. Build the runtime context handed to Claude for this turn:
    #    - A compact primer describing the API surface (for on-demand curl).
    #    - A short-lived Bearer token scoped to this user so curl can auth.
    #    - Base URL that the subprocess can reach the API at (localhost:8000).
    api_token = create_access_token(subject=str(user.id), extra={"purpose": "companion"})
    primer = _API_PRIMER.format(display_name=user.display_name, user_id=user.id)

    try:
        result = await run_claude_prompt(
            prompt=payload.content,
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
    assistant_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content_md=result.result,
        tool_calls=result.raw.get("tool_use") or result.raw.get("tool_calls"),
        tool_results=result.raw.get("tool_result_summary"),
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
