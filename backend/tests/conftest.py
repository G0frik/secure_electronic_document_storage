"""Shared pytest fixtures.

Phase 7+ — tests run against a **separate** database from the dev stack.
The autouse `_isolate_state` fixture TRUNCATEs everything, so running pytest
against the dev DB would wipe `flask seed-dev` users on every test session.

The test DB URL comes from `settings.effective_test_database_url`, which:
  1. Honours `TEST_DATABASE_URL` env var when set, or
  2. Derives `<DATABASE_URL>_test` (swaps the db name to `<name>_test`).

Bootstrap: `make test` runs `make ensure-test-db` first to CREATE DATABASE
+ alembic upgrade on the test DB if it doesn't exist yet.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from app.app_factory import create_app
from app.config import settings
from app.extensions import db as _db
from app.extensions import limiter as _limiter
from app.models.user import Department, Role, User
from app.services import passwords, storage

# Compute the test DB URL ONCE at module load — before any test fixture mutates
# settings.database_url. Doing it lazily inside the fixture would re-derive
# `<url>_test_test_test…` because each iteration starts from the already-
# rewritten value.
_DEV_DATABASE_URL = settings.database_url
_TEST_DATABASE_URL = settings.effective_test_database_url
_DEV_MINIO_BUCKET = settings.minio_bucket
_TEST_MINIO_BUCKET = settings.effective_test_minio_bucket

if _TEST_DATABASE_URL == _DEV_DATABASE_URL:
    raise RuntimeError(
        "Refusing to run tests against the dev/prod database. "
        "Set TEST_DATABASE_URL to a separate database "
        "(default: <DATABASE_URL>_test). Run `make ensure-test-db` to create it."
    )
if _TEST_MINIO_BUCKET == _DEV_MINIO_BUCKET:
    raise RuntimeError(
        "Refusing to run tests against the dev/prod MinIO bucket. "
        "Set TEST_MINIO_BUCKET to a separate bucket "
        "(default: <MINIO_BUCKET>-test)."
    )

# Pin the engine + object store to test-only locations for the entire session.
settings.database_url = _TEST_DATABASE_URL
settings.minio_bucket = _TEST_MINIO_BUCKET

# Phase 11 — keep the NDJSON event sink off the host FS during tests, and
# don't try to send emails through Mailhog from inside pytest.
settings.event_log_path = ""
settings.notifications_email_enabled = False


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    application = create_app()
    application.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    _limiter.enabled = False
    yield application
    _limiter.enabled = True


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture(autouse=True)
def _isolate_state(app: Flask) -> Generator[None, None, None]:
    """Clean DB + MinIO bucket before every test.

    NOTE: tests run against the same Postgres + MinIO as the dev stack. This
    fixture wipes them clean before each test, so don't run `pytest`
    against a DB/bucket that holds data you want to keep.
    """
    from app.services.policy import ensure_default_policies

    with app.app_context():
        _db.session.execute(
            text(
                "TRUNCATE TABLE notifications, tier_override_requests, "
                "file_tags, tags, share_links, shares, folders, user_totp, "
                "policy_evaluations, access_policies, classifications, "
                "audit_log, files, users, departments "
                "RESTART IDENTITY CASCADE"
            )
        )
        _db.session.commit()
        # Re-seed the 3 default global policies that the migration installs
        # (admin → restricted, user → confidential, guest → public).
        ensure_default_policies()
        # MinIO cleanup — best-effort
        try:
            storage.ensure_bucket()
            for key in list(storage.list_keys()):
                storage.delete(key)
        except Exception:
            pass
    yield


@pytest.fixture
def db_session(app: Flask) -> Generator:
    """App-context-bound DB session. Cleanup is handled by `_isolate_state`."""
    with app.app_context():
        try:
            yield _db.session
        finally:
            _db.session.rollback()
            _db.session.remove()


@pytest.fixture
def csrf_token(client: FlaskClient) -> str:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return response.json["csrf_token"]


@pytest.fixture
def seeded_admin(db_session) -> User:
    dept = Department(name="engineering")
    db_session.add(dept)
    db_session.flush()
    user = User(
        email="admin@docstore.app",
        password_hash=passwords.hash_password("AdminPassword123!"),  # noqa: S106
        role=Role.ADMIN,
        department_id=dept.id,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def seeded_other_user(db_session) -> User:
    """A second non-admin user, used for cross-owner access tests."""
    user = User(
        email="other@docstore.app",
        password_hash=passwords.hash_password("OtherPassword123!"),  # noqa: S106
        role=Role.USER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def seeded_user(db_session) -> User:
    """A regular (non-admin) user with a department. Used for Phase 5 RBAC tests
    where the caller must NOT have the admin bypass.
    """
    dept = db_session.query(Department).filter_by(name="marketing").first()
    if dept is None:
        dept = Department(name="marketing")
        db_session.add(dept)
        db_session.flush()
    user = User(
        email="alice@docstore.app",
        password_hash=passwords.hash_password("AlicePassword123!"),  # noqa: S106
        role=Role.USER,
        department_id=dept.id,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def seeded_guest(db_session) -> User:
    """A guest user — restricted to PUBLIC tier by default policy."""
    user = User(
        email="guest@docstore.app",
        password_hash=passwords.hash_password("GuestPassword123!"),  # noqa: S106
        role=Role.GUEST,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(autouse=True)
def _stub_celery_enqueue():
    """Replace Celery .delay() calls with no-ops so tests don't actually push
    to Redis. Tests that want to invoke the real task do so directly via the
    underlying service.
    """
    import unittest.mock

    with unittest.mock.patch("app.tasks.classification.classify_file.delay"), \
         unittest.mock.patch(
             "app.tasks.notifications.send_email_for_notification.delay"
         ):
        yield


@pytest.fixture
def logged_in_admin(client, db_session, seeded_admin, csrf_token) -> User:
    """Logs `seeded_admin` in via the real /login endpoint and returns the user.
    The test client retains the session cookie for subsequent calls.
    """
    response = client.post(
        "/api/auth/login",
        json={"email": seeded_admin.email, "password": "AdminPassword123!"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.data
    return seeded_admin


@pytest.fixture
def logged_in_user(client, db_session, seeded_user, csrf_token) -> User:
    """Logs in a regular non-admin user. Used for Phase 5 RBAC tests where the
    admin bypass would defeat the policy check.
    """
    response = client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.data
    return seeded_user
