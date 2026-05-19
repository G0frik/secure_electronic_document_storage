"""Tests for /api/auth/* endpoints."""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.models.audit import AuditLog
from app.services import passwords


def _post_json(client, url, body, csrf_token=None):  # type: ignore[no-untyped-def]
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    return client.post(url, json=body, headers=headers)


def test_csrf_endpoint_sets_cookie(client) -> None:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    assert "csrf_token" in response.json
    assert "csrf_token" in response.headers.get("Set-Cookie", "")


def test_login_without_csrf_is_rejected(client, db_session, seeded_admin) -> None:
    response = _post_json(
        client,
        "/api/auth/login",
        {"email": seeded_admin.email, "password": "AdminPassword123!"},
    )
    assert response.status_code == 403


def test_login_success(client, db_session, seeded_admin, csrf_token) -> None:
    response = _post_json(
        client,
        "/api/auth/login",
        {"email": seeded_admin.email, "password": "AdminPassword123!"},
        csrf_token=csrf_token,
    )
    assert response.status_code == 200, response.data
    assert response.json["email"] == seeded_admin.email
    assert response.json["role"] == "admin"

    # Audit row written
    rows = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "auth.login.success")
    ).all()
    assert len(rows) == 1


def test_login_wrong_password(client, db_session, seeded_admin, csrf_token) -> None:
    response = _post_json(
        client,
        "/api/auth/login",
        {"email": seeded_admin.email, "password": "wrong-pw"},
        csrf_token=csrf_token,
    )
    assert response.status_code == 401
    assert response.json["error"] == "invalid_credentials"

    rows = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "auth.login.failure")
    ).all()
    assert len(rows) == 1


def test_login_unknown_user_generic_error(client, db_session, csrf_token) -> None:
    response = _post_json(
        client,
        "/api/auth/login",
        {"email": "nobody@docstore.app", "password": "whatever-long"},
        csrf_token=csrf_token,
    )
    assert response.status_code == 401
    assert response.json["error"] == "invalid_credentials"


def test_me_requires_auth(client) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_after_login(client, db_session, seeded_admin, csrf_token) -> None:
    _post_json(
        client,
        "/api/auth/login",
        {"email": seeded_admin.email, "password": "AdminPassword123!"},
        csrf_token=csrf_token,
    )
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json["email"] == seeded_admin.email


def test_logout_clears_session(client, db_session, seeded_admin, csrf_token) -> None:
    _post_json(
        client,
        "/api/auth/login",
        {"email": seeded_admin.email, "password": "AdminPassword123!"},
        csrf_token=csrf_token,
    )
    response = _post_json(client, "/api/auth/logout", {}, csrf_token=csrf_token)
    assert response.status_code == 200

    # Subsequent /me must be 401
    assert client.get("/api/auth/me").status_code == 401

    rows = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "auth.logout")
    ).all()
    assert len(rows) == 1


def test_register_in_dev_mode(client, db_session, csrf_token, monkeypatch) -> None:
    monkeypatch.setattr(settings, "flask_env", "development")
    monkeypatch.setattr(settings, "allow_public_registration", True)
    monkeypatch.setattr(settings, "hibp_enabled", False)
    response = _post_json(
        client,
        "/api/auth/register",
        {"email": "new@docstore.app", "password": "NewLongPassword123!"},
        csrf_token=csrf_token,
    )
    assert response.status_code == 201, response.data
    assert response.json["email"] == "new@docstore.app"


def test_register_blocked_without_admin_in_prod(
    client, db_session, csrf_token, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "flask_env", "production")
    monkeypatch.setattr(settings, "allow_public_registration", False)
    monkeypatch.setattr(settings, "hibp_enabled", False)
    response = _post_json(
        client,
        "/api/auth/register",
        {"email": "x@docstore.app", "password": "AnyLongPassword123!"},
        csrf_token=csrf_token,
    )
    assert response.status_code == 401


def test_register_rejects_weak_password(
    client, db_session, csrf_token, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "flask_env", "development")
    monkeypatch.setattr(settings, "allow_public_registration", True)
    monkeypatch.setattr(settings, "hibp_enabled", False)
    response = _post_json(
        client,
        "/api/auth/register",
        {"email": "short@docstore.app", "password": "short"},
        csrf_token=csrf_token,
    )
    assert response.status_code == 422
    assert response.json["error"] == "weak_password"
    assert response.json["code"] == "too_short"


def test_password_hashing_helper(db_session) -> None:
    """Sanity check on the fixture pre-hash, in case Argon2 params change."""
    user_hash = passwords.hash_password("AdminPassword123!")  # noqa: S106
    assert passwords.verify_password("AdminPassword123!", user_hash)
