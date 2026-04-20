"""Companion conversation, messages, and tasks."""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class CompanionConversation(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "companion_conversations"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    related_tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True
    )
    persona_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True
    )


class ConversationMessage(Base, IdMixin, TimestampMixin):
    __tablename__ = "conversation_messages"

    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("companion_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    skill_invoked: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_calls: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    attachments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class Task(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "tasks"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    priority: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    related_event_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("application_events.id", ondelete="SET NULL"), nullable=True
    )
