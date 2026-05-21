"""Folder model — pure metadata. MinIO has no folders; this just lets users
organize and share groups of files.

Phase 7. Folders form a tree per owner (`parent_id` references another
folder of the same owner, or NULL for root-level). Sharing a folder
propagates access to every descendant file at query time.
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
    from app.models.file import File
    from app.models.user import User


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Phase 9 — soft delete. Folders are kept hard-delete-when-empty for now;
    # this column exists so a future cascade-trash story has a place to land.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    owner: Mapped[User] = relationship()
    # Self-referential parent link; children are fetched via service-layer queries.
    parent: Mapped[Folder | None] = relationship(remote_side="Folder.id")
    files: Mapped[list[File]] = relationship(back_populates="folder")

    def __repr__(self) -> str:
        return f"<Folder {self.name} owner={self.owner_id}>"
