"""User and Department models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base

if TYPE_CHECKING:
    from app.models.audit import AuditLog
    from app.models.file import File


class Role(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    users: Mapped[list[User]] = relationship(back_populates="department")

    def __repr__(self) -> str:
        return f"<Department {self.name}>"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
    )
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=Role.USER,
        server_default=Role.USER.value,
    )
    is_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Phase 13 — set by admin force-logout. Sessions whose `issued_at` is
    # earlier than this timestamp are rejected on the next request.
    session_invalid_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Phase 12 — storage quota. `used_bytes` is denormalised; the upload +
    # hard-delete paths increment/decrement it inline, and a Celery task
    # recomputes it nightly as drift protection.
    quota_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=str(2 * 1024 * 1024 * 1024)
    )
    used_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    department: Mapped[Department | None] = relationship(back_populates="users")
    audit_events: Mapped[list[AuditLog]] = relationship(back_populates="actor")
    files: Mapped[list[File]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"
