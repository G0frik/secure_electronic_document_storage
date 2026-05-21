"""Classification model — sensitivity tier per file (per version).

Phase 4: one row per file. Phase 10 (versioning) will add the `version`
column to a unique constraint on `(file_id, version)`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.file import File


class ClassificationTier(str, enum.Enum):
    """Mirrors classifier_core.Tier (kept separate so the model doesn't pull
    classifier deps into the web process)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ClassificationStatus(str, enum.Enum):
    PENDING = "pending"  # row inserted at upload, task not yet started
    RUNNING = "running"  # worker picked it up
    COMPLETED = "completed"
    FAILED = "failed"


class Classification(Base):
    __tablename__ = "classifications"
    __table_args__ = (UniqueConstraint("file_id", "version", name="uq_classifications_file_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Always 1 in Phase 4; Phase 10 starts using this for file versioning.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    status: Mapped[ClassificationStatus] = mapped_column(
        Enum(ClassificationStatus, name="classification_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ClassificationStatus.PENDING,
        server_default=ClassificationStatus.PENDING.value,
        index=True,
    )

    # Tier columns are NULL while pending/running; populated when COMPLETED.
    final_tier: Mapped[ClassificationTier | None] = mapped_column(
        Enum(ClassificationTier, name="classification_tier", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    zero_shot_tier: Mapped[ClassificationTier | None] = mapped_column(
        Enum(ClassificationTier, name="classification_tier", values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=True,
    )
    presidio_tier: Mapped[ClassificationTier | None] = mapped_column(
        Enum(ClassificationTier, name="classification_tier", values_callable=lambda e: [m.value for m in e], create_type=False),
        nullable=True,
    )

    raw_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    categories_triggered: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    presidio_entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    classifier_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    file: Mapped[File] = relationship(back_populates="classifications")

    def __repr__(self) -> str:
        return f"<Classification file={self.file_id} status={self.status.value} tier={self.final_tier}>"
