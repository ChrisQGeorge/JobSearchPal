"""Pydantic models for the Companion chat endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: Optional[str] = None
    summary: Optional[str] = None
    pinned: bool = False
    related_tracked_job_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: int
    role: str
    content_md: Optional[str] = None
    skill_invoked: Optional[str] = None
    tool_calls: Optional[Any] = None
    tool_results: Optional[Any] = None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut] = Field(default_factory=list)
    claude_session_id: Optional[str] = None


class CreateConversationIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    related_tracked_job_id: Optional[int] = None


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    # GeneratedDocument ids the user wants inlined for this turn's context.
    # The frontend uploads files via POST /documents/upload first, then passes
    # the resulting ids here so the Companion can read them alongside the
    # message text. Silently skipped if the doc doesn't belong to the user.
    attached_document_ids: Optional[list[int]] = None


class SendMessageOut(BaseModel):
    """Response shape for POST /conversations/{id}/messages."""
    user_message: MessageOut
    assistant_message: MessageOut
    conversation: ConversationSummary
    # Surface useful Claude metadata for the UI (cost display, etc.).
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    num_turns: Optional[int] = None
