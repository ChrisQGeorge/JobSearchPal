"""Generated documents, document edits, and writing samples."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class GeneratedDocument(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "generated_documents"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tracked_job_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("tracked_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_structured: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_version_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("generated_documents.id", ondelete="SET NULL"), nullable=True
    )
    humanized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    humanized_from_samples: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    persona_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True
    )
    prompt_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_skill: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class DocumentEdit(Base, IdMixin, TimestampMixin):
    __tablename__ = "document_edits"

    generated_document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("generated_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    editor: Mapped[str] = mapped_column(String(16), nullable=False)  # user / companion
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    selection_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    selection_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    replacement_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WritingSample(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "writing_samples"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    style_signals: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class CoverLetterSnippet(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """Reusable cover-letter snippet — opening hooks, bridges, closes, etc.

    The user maintains a small library of voice-matched fragments they
    like, and the tailor / Companion can pull a few in by kind/tag when
    drafting cover letters so the model isn't inventing fresh openers
    every time."""

    __tablename__ = "cover_letter_snippets"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
