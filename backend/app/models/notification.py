"""Notification model — per-recipient in-app feed entry (Phase 11).

Each row is "this user has been notified about this audit event."
`audit_log_id` is the FK back to the canonical event store (we reuse
`audit_log` rather than introducing a separate `events` table — the
schema overlaps almost completely, see decisions log in
[[Roadmap/Phase Tracker]]).

`read_at` toggles between "unread" and "read" states. We don't soft-delete
notifications; the cleanup task in Phase 9 already handles retention if
we ever need it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.audit import AuditLog
    from app.models.user import User


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    audit_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_log.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Denormalised for the feed UI so we don't have to JOIN audit_log on every
    # /api/notifications call. Source of truth is still the audit row.
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str | None] = mapped_column(String(512), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="info"
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    recipient: Mapped[User] = relationship()
    audit_log: Mapped[AuditLog | None] = relationship()

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __repr__(self) -> str:
        state = "read" if self.is_read else "unread"
        return f"<Notification {self.action_type} → {self.recipient_user_id} {state}>"
