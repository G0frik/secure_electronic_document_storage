"""Admin operations on user accounts (Phase 13).

Every state change goes through audit so the global event stream (Phase 11)
captures the admin's actions for SIEM ingestion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.user import Department, Role, User, UserStatus
from app.services import audit

log = get_logger(__name__)


class AdminUserError(Exception):
    """Base class for admin-user operation failures."""


class UnknownDepartmentError(AdminUserError):
    """Referenced department_id doesn't exist."""


class LastAdminError(AdminUserError):
    """Refusing to demote / disable the last remaining admin."""


# --- Queries ---


def list_users() -> list[User]:
    return list(db.session.scalars(select(User).order_by(User.email)))


def get(user_id: uuid.UUID) -> User | None:
    return db.session.get(User, user_id)


def _count_active_admins() -> int:
    return (
        db.session.scalar(
            select(db.func.count())
            .select_from(User)
            .where(
                User.role == Role.ADMIN, User.status == UserStatus.ACTIVE
            )
        )
        or 0
    )


# --- Mutations ---


def update_role(*, target: User, new_role: Role, actor: User) -> User:
    """Change a user's role. Refuses to demote the last active admin."""
    if target.role == new_role:
        return target
    if target.role == Role.ADMIN and new_role != Role.ADMIN:
        if _count_active_admins() <= 1:
            raise LastAdminError("Cannot demote the last active admin.")
    previous = target.role.value
    target.role = new_role
    audit.record(
        "admin.user.role_changed",
        actor=actor,
        target_type="user",
        target_id=target.id,
        metadata={
            "email": target.email,
            "previous_role": previous,
            "new_role": new_role.value,
        },
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()
    return target


def update_department(
    *, target: User, department_id: uuid.UUID | None, actor: User
) -> User:
    if department_id is not None:
        dept = db.session.get(Department, department_id)
        if dept is None:
            raise UnknownDepartmentError("Unknown department.")
    previous = str(target.department_id) if target.department_id else None
    target.department_id = department_id
    audit.record(
        "admin.user.department_changed",
        actor=actor,
        target_type="user",
        target_id=target.id,
        metadata={
            "email": target.email,
            "previous_department_id": previous,
            "new_department_id": str(department_id) if department_id else None,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return target


def update_quota(*, target: User, quota_bytes: int, actor: User) -> User:
    if quota_bytes < 0:
        raise AdminUserError("quota_bytes must be >= 0.")
    previous = target.quota_bytes
    target.quota_bytes = quota_bytes
    audit.record(
        "admin.user.quota_changed",
        actor=actor,
        target_type="user",
        target_id=target.id,
        metadata={
            "email": target.email,
            "previous_quota_bytes": previous,
            "new_quota_bytes": quota_bytes,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return target


def update_status(*, target: User, new_status: UserStatus, actor: User) -> User:
    """Change account status. Disabling the last active admin is blocked."""
    if target.status == new_status:
        return target
    if (
        new_status != UserStatus.ACTIVE
        and target.role == Role.ADMIN
        and target.status == UserStatus.ACTIVE
        and _count_active_admins() <= 1
    ):
        raise LastAdminError("Cannot disable / lock the last active admin.")
    previous = target.status.value
    target.status = new_status
    # Disabling or locking a user also force-logs them out so an existing
    # session can't keep working.
    if new_status != UserStatus.ACTIVE:
        target.session_invalid_before = datetime.now(timezone.utc)
    audit.record(
        "admin.user.status_changed",
        actor=actor,
        target_type="user",
        target_id=target.id,
        metadata={
            "email": target.email,
            "previous_status": previous,
            "new_status": new_status.value,
        },
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()
    return target


def update_is_manager(*, target: User, is_manager: bool, actor: User) -> User:
    if target.is_manager == is_manager:
        return target
    target.is_manager = is_manager
    audit.record(
        "admin.user.is_manager_changed",
        actor=actor,
        target_type="user",
        target_id=target.id,
        metadata={
            "email": target.email,
            "new_is_manager": is_manager,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return target


def force_logout(*, target: User, actor: User) -> User:
    """Bump `session_invalid_before` to now. Every existing session for the
    target user is treated as expired on the next request.
    """
    target.session_invalid_before = datetime.now(timezone.utc)
    audit.record(
        "admin.user.force_logout",
        actor=actor,
        target_type="user",
        target_id=target.id,
        metadata={
            "email": target.email,
            "invalidated_at": target.session_invalid_before.isoformat(),
        },
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()
    return target


# --- Audit log slice ---


def audit_for(target: User, *, limit: int = 100):  # type: ignore[no-untyped-def]
    """All audit rows where this user is either the actor or the target.
    Newest first. Used by the admin per-user audit panel.
    """
    from app.models.audit import AuditLog

    return list(
        db.session.scalars(
            select(AuditLog)
            .where(
                (AuditLog.actor_user_id == target.id)
                | (AuditLog.target_id == target.id)
            )
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
    )
