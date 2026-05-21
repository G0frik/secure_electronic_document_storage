"""ShareLink model — single-file external "magic link" sharing.

Phase 8. Lets a logged-in user mint a tokenised URL that anyone with the
link can use to download a single file, optionally bounded by expiry and
use count. The raw token is shown to the creator exactly once; the DB
stores only its SHA-256 hash, so a DB leak doesn't expose live links
(same threat-model trick we use for passwords / API keys at the big
cloud providers).

Token entropy: `secrets.token_urlsafe(32)` → 256 bits → uncrackable
either online or offline. Hashing is anti-leak, not anti-brute-force, so
SHA-256 is the right primitive (fast, allows indexed lookup).

Validity at access time = all four conditions:
  * `revoked_at IS NULL`
  * `expires_at IS NULL OR expires_at > now()`
  * `max_uses IS NULL OR use_count < max_uses`
  * the referenced file still exists

The owning file's classification still applies — RESTRICTED files cannot
get external links unless an admin overrides.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.user import User


class ShareLink(Base):
    __tablename__ = "share_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256(token) hex — 64 chars. UNIQUE so the lookup is a B-tree probe.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    file: Mapped[File] = relationship()
    created_by: Mapped[User | None] = relationship()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def __repr__(self) -> str:
        state = "active" if self.is_active else "revoked"
        used = (
            f"{self.use_count}/{self.max_uses}"
            if self.max_uses is not None
            else f"{self.use_count}/∞"
        )
        return f"<ShareLink file={self.file_id} {used} uses {state}>"
