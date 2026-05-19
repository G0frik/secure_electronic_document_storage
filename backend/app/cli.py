"""Flask CLI commands."""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from app.extensions import db
from app.logging_config import get_logger
from app.models.user import Department, Role
from app.services import passwords, users
from app.services.users import UserAlreadyExistsError

log = get_logger(__name__)

DEV_ADMIN_EMAIL = "admin@example.com"
DEV_ADMIN_PASSWORD = "ChangeMeNow123!"  # noqa: S105 — dev-only seed credential
DEV_DEPARTMENTS = ["engineering", "hr", "marketing"]


def register_cli(app: Flask) -> None:
    app.cli.add_command(seed_dev)


@click.command("seed-dev")
@with_appcontext
def seed_dev() -> None:
    """Seed development data: 3 departments + 1 admin user. Idempotent."""
    created_depts = []
    for name in DEV_DEPARTMENTS:
        if db.session.query(Department).filter_by(name=name).first() is None:
            db.session.add(Department(name=name))
            created_depts.append(name)
    if created_depts:
        db.session.commit()
        click.echo(f"Created departments: {', '.join(created_depts)}")
    else:
        click.echo("Departments already exist.")

    existing = users.get_user_by_email(DEV_ADMIN_EMAIL)
    if existing is not None:
        click.echo(f"Admin user {DEV_ADMIN_EMAIL} already exists; skipping.")
        return

    # Skip HIBP for the dev seed password (well-known + dev-only).
    from app.config import settings

    original_hibp = settings.hibp_enabled
    settings.hibp_enabled = False
    try:
        users.create_user(
            email=DEV_ADMIN_EMAIL,
            password=DEV_ADMIN_PASSWORD,
            role=Role.ADMIN,
        )
    except UserAlreadyExistsError:
        click.echo(f"Admin user {DEV_ADMIN_EMAIL} already exists; skipping.")
        return
    finally:
        settings.hibp_enabled = original_hibp

    # Validate seed password meets length policy (so we catch dev-config drift)
    try:
        passwords.validate_password_policy(DEV_ADMIN_PASSWORD)
    except passwords.WeakPasswordError as exc:
        click.echo(f"WARNING: dev seed password failed policy: {exc}")

    click.echo("")
    click.echo("=" * 60)
    click.echo(f"  Dev admin user created: {DEV_ADMIN_EMAIL}")
    click.echo(f"  Password:               {DEV_ADMIN_PASSWORD}")
    click.echo("  CHANGE THIS BEFORE DEPLOYING.")
    click.echo("=" * 60)
