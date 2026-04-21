"""Generic entity-link table — polymorphic many-to-many across history entities.

Used when a strict typed join table would be overkill. The (from_entity_type,
from_entity_id) pair points at the owning entity; (to_entity_type, to_entity_id)
points at the related one. Directionality is semantic (we use it for the
UI's "related items" panel) but queries can read either direction.

Supported entity types: work, education, course, skill, certification,
project, publication, presentation, achievement, volunteer, custom, contact,
tracked_job, interview_round.

For Skill <-> Work and Skill <-> Course we use dedicated join tables with a
`usage_notes` column because those links carry more semantic weight.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class EntityLink(Base, IdMixin, TimestampMixin):
    __tablename__ = "entity_links"
    __table_args__ = (
        # A link is identified by the directed 4-tuple + relation. Keeps
        # accidental duplicates out.
        UniqueConstraint(
            "user_id",
            "from_entity_type",
            "from_entity_id",
            "to_entity_type",
            "to_entity_id",
            "relation",
            name="uq_entity_link",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    from_entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    to_entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    to_entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(32), nullable=False, default="related")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
