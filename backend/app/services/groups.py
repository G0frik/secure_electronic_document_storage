"""Group CRUD + membership service (Phase 13).

Group membership feeds into access-policy resolution — see
[services/policy.py::_resolve_policy]. The admin UI calls into here to
mint, rename, and delete groups, and to add / remove members.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.group import Group, UserGroup
from app.models.user import User
from app.services import audit

log = get_logger(__name__)


class GroupError(Exception):
    pass


class GroupConflictError(GroupError):
    pass


# --- Read ---


def list_all() -> list[Group]:
    return list(db.session.scalars(select(Group).order_by(Group.name)))


def get(group_id: uuid.UUID) -> Group | None:
    return db.session.get(Group, group_id)


def members_of(group: Group) -> list[User]:
    return list(
        db.session.scalars(
            select(User)
            .join(UserGroup, UserGroup.user_id == User.id)
            .where(UserGroup.group_id == group.id)
            .order_by(User.email)
        )
    )


def groups_of(user: User) -> list[Group]:
    return list(
        db.session.scalars(
            select(Group)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(UserGroup.user_id == user.id)
            .order_by(Group.name)
        )
    )


# --- CRUD ---


def create(*, name: str, description: str | None, actor: User) -> Group:
    name = (name or "").strip()
    if not name:
        raise GroupError("Group name cannot be empty.")
    if len(name) > 64:
        raise GroupError("Group name too long (max 64 chars).")
    if description is not None:
        description = description.strip() or None
        if description is not None and len(description) > 256:
            raise GroupError("Group description too long (max 256 chars).")
    group = Group(name=name, description=description)
    db.session.add(group)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise GroupConflictError(
            f"A group named {name!r} already exists."
        ) from None
    audit.record(
        "admin.group.created",
        actor=actor,
        target_type="group",
        target_id=group.id,
        metadata={"name": name, "description": description},
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return group


def update(
    *,
    group: Group,
    name: str | None,
    description: str | None,
    clear_description: bool,
    actor: User,
) -> Group:
    changed: dict = {}
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise GroupError("Group name cannot be empty.")
        if cleaned != group.name:
            changed["previous_name"] = group.name
            changed["new_name"] = cleaned
            group.name = cleaned
    if description is not None:
        description = description.strip() or None
    if clear_description:
        description = None
    if description != group.description and (
        description is not None or clear_description
    ):
        changed["previous_description"] = group.description
        changed["new_description"] = description
        group.description = description
    if not changed:
        return group
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise GroupConflictError("Group name conflict.") from None
    audit.record(
        "admin.group.updated",
        actor=actor,
        target_type="group",
        target_id=group.id,
        metadata={"changes": changed},
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return group


def delete(*, group: Group, actor: User) -> None:
    snapshot = {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
    }
    db.session.delete(group)
    audit.record(
        "admin.group.deleted",
        actor=actor,
        target_type="group",
        target_id=group.id,
        metadata=snapshot,
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()


# --- Membership ---


def add_member(*, group: Group, user: User, actor: User) -> bool:
    """Returns True if newly added, False if already a member."""
    existing = db.session.scalar(
        select(UserGroup).where(
            UserGroup.user_id == user.id, UserGroup.group_id == group.id
        )
    )
    if existing is not None:
        return False
    link = UserGroup(
        user_id=user.id, group_id=group.id, added_by_id=actor.id
    )
    db.session.add(link)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False  # racing add
    audit.record(
        "admin.group.member_added",
        actor=actor,
        target_type="group",
        target_id=group.id,
        metadata={"user_id": str(user.id), "email": user.email},
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return True


def remove_member(*, group: Group, user: User, actor: User) -> bool:
    """Returns True if removed, False if user wasn't a member."""
    existing = db.session.scalar(
        select(UserGroup).where(
            UserGroup.user_id == user.id, UserGroup.group_id == group.id
        )
    )
    if existing is None:
        return False
    db.session.delete(existing)
    audit.record(
        "admin.group.member_removed",
        actor=actor,
        target_type="group",
        target_id=group.id,
        metadata={"user_id": str(user.id), "email": user.email},
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return True
