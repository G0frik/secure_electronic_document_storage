"""Flask CLI commands."""

from __future__ import annotations

from dataclasses import dataclass

import click
from flask import Flask
from flask.cli import with_appcontext

from app.extensions import db
from app.logging_config import get_logger
from app.models.user import Department, Role
from app.services import passwords, users
from app.services.users import UserAlreadyExistsError

log = get_logger(__name__)

DEV_DEPARTMENTS = ["engineering", "hr", "marketing"]


@dataclass(frozen=True)
class _DevUser:
    email: str
    password: str
    role: Role
    department: str | None  # department name, or None for no department
    is_manager: bool = False


# Seeded users span every Phase-5 RBAC scenario:
#   admin               — bypass: reads every tier.
#   user (marketing)    — default policy: reads up to CONFIDENTIAL. Denied on RESTRICTED.
#   user (hr) manager   — same default policy; flagged manager for Phase 7+ share/owner UX.
#   user (engineering)  — same default policy; second non-admin for cross-user demos.
#   guest               — default policy: reads PUBLIC only.
DEV_USERS: list[_DevUser] = [
    _DevUser(
        email="admin@example.com",
        password="ChangeMeNow123!",  # noqa: S106
        role=Role.ADMIN,
        department="engineering",
    ),
    _DevUser(
        email="alice@example.com",
        password="AlicePassword123!",  # noqa: S106
        role=Role.USER,
        department="marketing",
    ),
    _DevUser(
        email="bob@example.com",
        password="BobPassword123!",  # noqa: S106
        role=Role.USER,
        department="hr",
        is_manager=True,
    ),
    _DevUser(
        email="carol@example.com",
        password="CarolPassword123!",  # noqa: S106
        role=Role.USER,
        department="engineering",
    ),
    _DevUser(
        email="dave@example.com",
        password="DavePassword123!",  # noqa: S106
        role=Role.GUEST,
        department=None,
    ),
]


def register_cli(app: Flask) -> None:
    app.cli.add_command(seed_dev)
    app.cli.add_command(reap_trash)
    app.cli.add_command(reap_file_versions)
    app.cli.add_command(recompute_quota)


@click.command("reap-trash")
@click.option(
    "--retention-days",
    default=30,
    show_default=True,
    help="Hard-delete files trashed before now() - retention_days.",
)
@with_appcontext
def reap_trash(retention_days: int) -> None:
    """Phase 9 — hard-delete files past the trash retention window. Equivalent
    to the `trash.reap` Celery task; intended for cron / manual sweeps.
    """
    from app.services import trash

    count = trash.reap_expired_trash(retention_days=retention_days)
    click.echo(f"Reaped {count} file(s) past the {retention_days}-day retention.")


@click.command("reap-file-versions")
@click.option(
    "--retention-days",
    default=30,
    show_default=True,
    help="Hard-delete historical file versions older than now() - retention_days.",
)
@with_appcontext
def reap_file_versions(retention_days: int) -> None:
    """Phase 15 — hard-delete file versions older than the retention window.
    Current versions are never touched. Equivalent to the
    `file_versions.reap` Celery task.
    """
    from app.services import file_versions

    count = file_versions.reap_expired_versions(retention_days=retention_days)
    click.echo(
        f"Reaped {count} version(s) past the {retention_days}-day retention."
    )


@click.command("recompute-quota")
@with_appcontext
def recompute_quota() -> None:
    """Phase 12 — recompute `used_bytes` for every user from
    `SUM(files.size_bytes)`. Cheap drift safety; equivalent to the
    `quota.recompute` Celery task.
    """
    from app.services import quota

    affected = quota.recompute_all()
    click.echo(f"Recomputed quota usage for {affected} user(s).")


@click.command("seed-dev")
@with_appcontext
def seed_dev() -> None:
    """Seed development data: 3 departments + 5 users covering every role/policy
    branch. Idempotent — existing rows are left alone.
    """
    # Departments
    created_depts: list[str] = []
    for name in DEV_DEPARTMENTS:
        if db.session.query(Department).filter_by(name=name).first() is None:
            db.session.add(Department(name=name))
            created_depts.append(name)
    if created_depts:
        db.session.commit()
        click.echo(f"Created departments: {', '.join(created_depts)}")
    else:
        click.echo("Departments already exist.")

    # Users. Skip HIBP for the dev seed passwords (well-known dev creds).
    from app.config import settings

    original_hibp = settings.hibp_enabled
    settings.hibp_enabled = False
    try:
        created_users: list[str] = []
        skipped_users: list[str] = []
        for spec in DEV_USERS:
            if users.get_user_by_email(spec.email) is not None:
                skipped_users.append(spec.email)
                continue

            # Resolve department (None → no department).
            dept_id = None
            if spec.department is not None:
                dept = db.session.query(Department).filter_by(name=spec.department).first()
                if dept is None:
                    click.echo(
                        f"WARNING: department {spec.department!r} missing for {spec.email}; "
                        "creating user without a department."
                    )
                else:
                    dept_id = dept.id

            try:
                users.create_user(
                    email=spec.email,
                    password=spec.password,
                    role=spec.role,
                    department_id=dept_id,
                    is_manager=spec.is_manager,
                )
            except UserAlreadyExistsError:
                skipped_users.append(spec.email)
                continue

            # Validate every seed password against the length policy so we
            # catch dev-config drift early.
            try:
                passwords.validate_password_policy(spec.password)
            except passwords.WeakPasswordError as exc:
                click.echo(f"WARNING: dev seed password for {spec.email} failed policy: {exc}")
            created_users.append(spec.email)
    finally:
        settings.hibp_enabled = original_hibp

    click.echo("")
    click.echo("=" * 72)
    click.echo("  Dev users")
    click.echo("=" * 72)
    for spec in DEV_USERS:
        marker = "+" if spec.email in created_users else "·"
        dept = spec.department or "—"
        mgr = " manager" if spec.is_manager else ""
        click.echo(
            f"  {marker} {spec.email:<24} {spec.role.value:<5}  dept={dept:<12}{mgr}"
        )
        click.echo(f"      password: {spec.password}")
    click.echo("")
    if created_users:
        click.echo(f"Created {len(created_users)} user(s): {', '.join(created_users)}")
    if skipped_users:
        click.echo(f"Already present: {', '.join(skipped_users)}")
    click.echo("CHANGE THESE PASSWORDS BEFORE DEPLOYING.")
    click.echo("=" * 72)
