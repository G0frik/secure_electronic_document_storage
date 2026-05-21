"""Department CRUD service (Phase 13)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.user import Department, User
from app.services import audit

log = get_logger(__name__)


class DepartmentError(Exception):
    pass


class DepartmentConflictError(DepartmentError):
    pass


class DepartmentInUseError(DepartmentError):
    """Refused to delete because users still reference it."""


def list_all() -> list[Department]:
    return list(db.session.scalars(select(Department).order_by(Department.name)))


def get(dept_id: uuid.UUID) -> Department | None:
    return db.session.get(Department, dept_id)


def create(*, name: str, actor: User) -> Department:
    name = (name or "").strip()
    if not name:
        raise DepartmentError("Department name cannot be empty.")
    if len(name) > 64:
        raise DepartmentError("Department name too long (max 64 chars).")
    dept = Department(name=name)
    db.session.add(dept)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise DepartmentConflictError(
            f"A department named {name!r} already exists."
        ) from None
    audit.record(
        "admin.department.created",
        actor=actor,
        target_type="department",
        target_id=dept.id,
        metadata={"name": name},
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return dept


def rename(*, dept: Department, name: str, actor: User) -> Department:
    name = (name or "").strip()
    if not name:
        raise DepartmentError("Department name cannot be empty.")
    if name == dept.name:
        return dept
    previous = dept.name
    dept.name = name
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise DepartmentConflictError(
            f"A department named {name!r} already exists."
        ) from None
    audit.record(
        "admin.department.renamed",
        actor=actor,
        target_type="department",
        target_id=dept.id,
        metadata={"previous_name": previous, "new_name": name},
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return dept


def delete(*, dept: Department, actor: User) -> None:
    """Refuse if any users still belong. Caller can reassign them first."""
    user_count = (
        db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.department_id == dept.id)
        )
        or 0
    )
    if user_count > 0:
        raise DepartmentInUseError(
            f"{user_count} user(s) still belong to this department."
        )
    snapshot = {"name": dept.name, "id": str(dept.id)}
    db.session.delete(dept)
    audit.record(
        "admin.department.deleted",
        actor=actor,
        target_type="department",
        target_id=dept.id,
        metadata=snapshot,
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()
