"""Share model — polymorphic (file | folder), additive grant of access.

Phase 7. A Share row says "user G has granted user R viewer-or-editor access
to a specific file or folder". A partial unique index enforces only one
*active* (revoked_at IS NULL) share per (target_type, target_id, recipient).

For folder shares, downstream files (recursively) are reachable via the
share — see `services/shares.py::user_accessible_file_ids`.

target_id is polymorphic — no FK constraint to a specific table. The
service layer validates the target exists and that the granter owns it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.user import User


class ShareTargetType(str, enum.Enum):
    FILE = "file"
    FOLDER = "folder"


class SharePermission(str, enum.Enum):
    VIEWER = "viewer"
    EDITOR = "editor"


class Share(Base):
    __tablename__ = "shares"
    __table_args__ = (
        CheckConstraint("granter_id <> recipient_id", name="ck_shares_granter_ne_recipient"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_type: Mapped[ShareTargetType] = mapped_column(
        Enum(
            ShareTargetType,
            name="share_target_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    granter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission: Mapped[SharePermission] = mapped_column(
        Enum(
            SharePermission,
            name="share_permission",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SharePermission.VIEWER,
        server_default=SharePermission.VIEWER.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    granter: Mapped[User] = relationship(foreign_keys=[granter_id])
    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id])

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def __repr__(self) -> str:
        state = "active" if self.is_active else "revoked"
        return (
            f"<Share {self.target_type.value}={self.target_id} "
            f"granter={self.granter_id} recipient={self.recipient_id} "
            f"{self.permission.value} {state}>"
        )
