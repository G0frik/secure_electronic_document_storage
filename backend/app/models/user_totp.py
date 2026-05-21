"""UserTotp model — per-user TOTP secret + recovery codes.

Phase 6 — TOTP-based 2FA. One row per user (UNIQUE on user_id). The TOTP
secret itself is encrypted at rest with the KEK (same envelope idea as
file DEKs, just inlined since the blob is tiny). Recovery codes are stored
as Argon2 hashes alongside a `used_at` marker so each code can only be
spent once.

Layout of the encrypted secret on disk:
    secret_ciphertext  — AES-GCM ciphertext of the base32 secret
    secret_nonce       — 12-byte GCM nonce
    secret_tag         — 16-byte GCM auth tag
    kek_version        — KEK version used to wrap (rotation hook, default 1)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, SmallInteger, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.user import User


class UserTotp(Base):
    __tablename__ = "user_totp"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # --- KEK-wrapped TOTP secret ---
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_tag: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")

    # --- State ---
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Recovery codes ---
    # List of {"hash": "<argon2>", "used_at": "<iso>|null"}. 10 codes generated
    # at setup time; each one can be spent exactly once.
    recovery_codes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship()

    def __repr__(self) -> str:
        state = "enabled" if self.enabled else "pending"
        return f"<UserTotp user={self.user_id} {state}>"
