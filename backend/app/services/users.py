"""User domain service. All user state changes go through here."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.extensions import db
from app.models.user import Role, User
from app.services import audit, passwords


class UserAlreadyExistsError(ValueError):
    pass


def get_user_by_email(email: str) -> User | None:
    return db.session.scalar(select(User).where(User.email == email.strip().lower()))


def get_user_by_id(user_id: uuid.UUID) -> User | None:
    return db.session.get(User, user_id)


def create_user(
    *,
    email: str,
    password: str,
    role: Role = Role.USER,
    department_id: uuid.UUID | None = None,
    is_manager: bool = False,
    actor: User | None = None,
) -> User:
    """Create a new user. Caller MUST have validated the password policy first."""
    normalised_email = email.strip().lower()
    if get_user_by_email(normalised_email) is not None:
        raise UserAlreadyExistsError(f"A user with email {normalised_email!r} already exists.")

    user = User(
        email=normalised_email,
        password_hash=passwords.hash_password(password),
        role=role,
        department_id=department_id,
        is_manager=is_manager,
    )
    db.session.add(user)
    db.session.flush()  # populate user.id for the audit row

    audit.record(
        "user.created",
        actor=actor,
        target_type="user",
        target_id=user.id,
        metadata={
            "email": normalised_email,
            "role": role.value,
            "is_manager": is_manager,
            "department_id": str(department_id) if department_id else None,
        },
        commit=False,
    )
    db.session.commit()
    return user


def update_last_login(user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    db.session.commit()
