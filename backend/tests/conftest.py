"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import text

from app.app_factory import create_app
from app.extensions import db as _db
from app.extensions import limiter as _limiter
from app.models.user import Department, Role, User
from app.services import passwords, storage


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    application = create_app()
    application.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    # Belt-and-braces: also flip the limiter flag (in case the config check is
    # short-circuited at a different layer).
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
    with app.app_context():
        _db.session.execute(
            text("TRUNCATE TABLE audit_log, files, users, departments RESTART IDENTITY CASCADE")
        )
        _db.session.commit()
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
