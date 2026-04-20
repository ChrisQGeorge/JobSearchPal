"""User, Persona, and ApiCredential."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class User(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    active_persona_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(
            "personas.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_users_active_persona",
        ),
        nullable=True,
    )
    preferences: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Persona(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "personas"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    tone_descriptors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    system_prompt: Mapped[str] = mapped_column(String(8000), nullable=False, default="")
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ApiCredential(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "api_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider", "label", name="uq_api_cred"),)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(String(2048), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
