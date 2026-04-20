"""Companion chat — conversations and message exchange via Claude Code CLI."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
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

    # 2. Invoke the Claude Code CLI. Thread multi-turn chat via --resume.
    try:
        result = await run_claude_prompt(
            prompt=payload.content,
            output_format="json",
            session_id=conv.claude_session_id,
            timeout_seconds=180,
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
