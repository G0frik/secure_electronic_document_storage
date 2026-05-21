"""Access policy + per-decision evaluation models.

Phase 5 — tier-based RBAC. A policy row says "users with this role
(optionally restricted to this department) may access files whose
classification tier is <= allowed_max_tier, with optional category
whitelist/blacklist".

Resolution: when checking access for (user, file), the most specific
matching policy wins (department-scoped > role-only). See
`services/policy.py::can_user_access`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import Base
from app.models.classification import ClassificationTier
from app.models.user import Role

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.user import Department, User


class PolicyDecision(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"


class AccessPolicy(Base):
    """One row = "role R in department D may read tier ≤ T".

    `department_id = NULL` means the policy applies regardless of the user's
    department (it's the default for that role).
    """

    __tablename__ = "access_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        nullable=False,
        index=True,
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Phase 13 — group targeting. A policy with `group_id` only applies to
    # members of that group. Resolution: group-targeted policies are
    # collected first; if any match, the most-permissive (highest
    # `allowed_max_tier`) wins. Falls back to department-scoped then global.
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    allowed_max_tier: Mapped[ClassificationTier] = mapped_column(
        Enum(
            ClassificationTier,
            name="classification_tier",
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        nullable=False,
    )
    # JSONB list[str] of category short names. NULL = no allow-list (all categories accepted).
    allowed_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # JSONB list[str] of category short names. NULL = no deny-list.
    denied_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    department: Mapped[Department | None] = relationship()
    created_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        scope = f"dept={self.department_id}" if self.department_id else "global"
        return f"<AccessPolicy role={self.role.value} {scope} max_tier={self.allowed_max_tier.value}>"


class PolicyEvaluation(Base):
    """Per-decision audit row. Written for every `can_user_access` call.

    Separate from `audit_log` because the cardinality is much higher and the
    schema (decision + reason + policy_id) is fixed — easier to query against
    for RBAC reports than a JSONB metadata field.
    """

    __tablename__ = "policy_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision: Mapped[PolicyDecision] = mapped_column(
        Enum(
            PolicyDecision,
            name="policy_decision",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    matched_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("access_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped[User | None] = relationship()
    file: Mapped[File | None] = relationship()

    def __repr__(self) -> str:
        return (
            f"<PolicyEvaluation user={self.user_id} file={self.file_id} "
            f"→ {self.decision.value} ({self.reason})>"
        )
