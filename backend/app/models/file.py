"""File model — opaque metadata for objects stored in MinIO.

Phase 2: no encryption (Phase 3 adds wrapped_dek/nonce/auth_tag columns),
no classification (Phase 4 adds the `classifications` table), no folders,
no shares.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, LargeBinary, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.classification import Classification
    from app.models.file_version import FileVersion
    from app.models.folder import Folder
    from app.models.user import User


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # Opaque storage identifier — what MinIO knows the object as.
    # Separated from `id` so backups / migrations / re-keying don't lose metadata.
    storage_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # SHA-256 of PLAINTEXT (not ciphertext) — useful for dedup and integrity.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # --- Soft delete (Phase 9) ---
    # When set, the row is in the user's trash. Listings/downloads/share-link
    # lookups all filter `deleted_at IS NULL`. Reaper hard-deletes rows older
    # than 30 days.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Folder placement (Phase 7) ---
    # NULL = root level. ON DELETE SET NULL so deleting a folder moves its
    # files back to root rather than cascading the destruction.
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # --- Envelope encryption (Phase 3) ---
    # Self-contained blob: dek_nonce(12) || dek_ciphertext(32) || dek_tag(16) = 60 B
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # AES-GCM nonce for the file body (12 B)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # AES-GCM auth tag for the file body (16 B), stored separately from MinIO bytes
    auth_tag: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # KEK rotation hook — every row records the KEK version used to wrap its DEK
    kek_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")

    # --- Versioning (Phase 15) ---
    # Counter for the *current* version's number. Starts at 1; bumps each time
    # the owner uploads a new version (the old content snapshots into
    # `file_versions` and the `files` row is overwritten in place).
    current_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1"
    )

    owner: Mapped[User] = relationship(back_populates="files")
    folder: Mapped[Folder | None] = relationship(back_populates="files")
    classifications: Mapped[list[Classification]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    versions: Mapped[list[FileVersion]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FileVersion.version_number.desc()",
    )

    def __repr__(self) -> str:
        return f"<File {self.original_filename} ({self.size_bytes}B)>"
