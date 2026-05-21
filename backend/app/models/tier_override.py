"""Tier-override request model (Phase 10).

A user can disagree with the classifier's auto-tier and request a manual
override. The owner files the request with a justification; an admin
approves or denies. On approval the system inserts a NEW Classification
row pinned to the requested tier (the original auto-tier row stays for
audit), so policy queries naturally start returning the override via the
existing `get_latest` lookup ordered by `version`.

Partial unique index in the migration (`WHERE status = 'pending'`) makes
sure a single file can have at most one *pending* request open at a
time — historical approved / denied rows are preserved.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base
from app.models.classification import ClassificationTier

if TYPE_CHECKING:
    from app.models.classification import Classification
    from app.models.file import File
    from app.models.user import User


class OverrideStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class TierOverrideRequest(Base):
    __tablename__ = "tier_override_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    classification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_tier: Mapped[ClassificationTier] = mapped_column(
        Enum(
            ClassificationTier,
            name="classification_tier",
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        nullable=False,
    )
    requested_tier: Mapped[ClassificationTier] = mapped_column(
        Enum(
            ClassificationTier,
            name="classification_tier",
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        nullable=False,
    )
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OverrideStatus] = mapped_column(
        Enum(
            OverrideStatus,
            name="tier_override_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=OverrideStatus.PENDING,
        server_default=OverrideStatus.PENDING.value,
        index=True,
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    file: Mapped[File] = relationship()
    classification: Mapped[Classification | None] = relationship()
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])

    def __repr__(self) -> str:
        return (
            f"<TierOverride file={self.file_id} {self.current_tier.value}→"
            f"{self.requested_tier.value} {self.status.value}>"
        )
