"""Phase 6 — /api/auth/totp/* + 2-step login flow API tests."""

from __future__ import annotations

import pyotp
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.user_totp import UserTotp
from app.services import totp


def _login_password(client, csrf_token, email, password):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )


def _totp_challenge(client, csrf_token, code):
    return client.post(
        "/api/auth/totp/challenge",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )


# --- Enrollment ---


def test_status_when_no_enrollment(client, db_session, logged_in_admin) -> None:
    resp = client.get("/api/auth/totp/status")
    assert resp.status_code == 200
    assert resp.json == {
        "enabled": False,
        "pending_enrollment": False,
        "remaining_recovery_codes": 0,
        "last_used_at": None,
    }


def test_setup_returns_uri_and_codes(client, db_session, logged_in_admin, csrf_token) -> None:
    resp = client.post(
        "/api/auth/totp/setup",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 201
    body = resp.json
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["secret"]
    assert len(body["recovery_codes"]) == 10
    # Row was created, still disabled
    row = db_session.scalar(select(UserTotp).where(UserTotp.user_id == logged_in_admin.id))
    assert row is not None
    assert row.enabled is False
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "auth.totp.setup_started")
    ).all()
    assert len(audits) == 1


def test_verify_enables_with_valid_code(client, db_session, logged_in_admin, csrf_token) -> None:
    setup_resp = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token})
    secret = setup_resp.json["secret"]
    code = pyotp.TOTP(secret).now()
    resp = client.post(
        "/api/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json == {"enabled": True}

    status = client.get("/api/auth/totp/status").json
    assert status["enabled"] is True
    assert status["remaining_recovery_codes"] == 10


def test_verify_rejects_wrong_code(client, db_session, logged_in_admin, csrf_token) -> None:
    client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token})
    resp = client.post(
        "/api/auth/totp/verify",
        json={"code": "000000"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json["error"] == "totp_verify_failed"


def test_setup_rejected_when_already_enabled(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    setup = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token}).json
    code = pyotp.TOTP(setup["secret"]).now()
    client.post(
        "/api/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    # Second setup should be rejected
    resp = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 409


def test_disable_requires_code(client, db_session, logged_in_admin, csrf_token) -> None:
    setup = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token}).json
    code = pyotp.TOTP(setup["secret"]).now()
    client.post(
        "/api/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    # Wrong code
    bad = client.post(
        "/api/auth/totp/disable",
        json={"code": "000000"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert bad.status_code == 400

    # Right code — must be a different code from the one used for enable() if
    # the second is still inside the 30s window; pyotp.now() returns the same
    # code throughout, which is fine — replay isn't blocked by the service.
    fresh = pyotp.TOTP(setup["secret"]).now()
    ok = client.post(
        "/api/auth/totp/disable",
        json={"code": fresh},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert ok.status_code == 200
    assert ok.json == {"enabled": False}


# --- 2-step login flow ---


def test_login_without_totp_returns_user(client, db_session, seeded_admin, csrf_token) -> None:
    resp = _login_password(client, csrf_token, seeded_admin.email, "AdminPassword123!")
    assert resp.status_code == 200
    # Plain user payload, NOT requires_totp
    assert "requires_totp" not in resp.json
    assert resp.json["two_factor_enabled"] is False


def test_login_with_totp_returns_requires_totp(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    # Enable 2FA first
    setup = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token}).json
    code = pyotp.TOTP(setup["secret"]).now()
    client.post(
        "/api/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    # Log out
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})

    # Log in again with password only — should land at the TOTP step
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    resp = _login_password(client, new_csrf, logged_in_admin.email, "AdminPassword123!")
    assert resp.status_code == 200
    assert resp.json == {"requires_totp": True}

    # Hitting /api/auth/me is forbidden in the half-authenticated state
    me = client.get("/api/auth/me")
    assert me.status_code == 401

    # Submit the TOTP code → full session
    fresh = pyotp.TOTP(setup["secret"]).now()
    challenge = _totp_challenge(client, new_csrf, fresh)
    assert challenge.status_code == 200
    assert challenge.json["email"] == logged_in_admin.email

    # /me now works
    me2 = client.get("/api/auth/me")
    assert me2.status_code == 200


def test_challenge_with_recovery_code_consumes_it(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    setup = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token}).json
    code = pyotp.TOTP(setup["secret"]).now()
    client.post(
        "/api/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    recovery_code = setup["recovery_codes"][0]

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    _login_password(client, new_csrf, logged_in_admin.email, "AdminPassword123!")

    # Use the recovery code at the challenge step
    challenge = _totp_challenge(client, new_csrf, recovery_code)
    assert challenge.status_code == 200

    # Recovery count drops by 1
    status = client.get("/api/auth/totp/status").json
    assert status["remaining_recovery_codes"] == 9


def test_challenge_without_pending_returns_401(client, db_session, csrf_token) -> None:
    """No pending session = no challenge accepted."""
    resp = _totp_challenge(client, csrf_token, "000000")
    assert resp.status_code == 401


def test_challenge_with_wrong_code_keeps_pending_state(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    setup = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token}).json
    code = pyotp.TOTP(setup["secret"]).now()
    client.post(
        "/api/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})

    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    _login_password(client, new_csrf, logged_in_admin.email, "AdminPassword123!")

    bad = _totp_challenge(client, new_csrf, "000000")
    assert bad.status_code == 401

    # /me still forbidden (still half-authenticated)
    assert client.get("/api/auth/me").status_code == 401

    # Correct code still works (the bad guess did not destroy the pending state)
    fresh = pyotp.TOTP(setup["secret"]).now()
    ok = _totp_challenge(client, new_csrf, fresh)
    assert ok.status_code == 200

    # Audit row for the failed challenge exists
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "auth.totp.challenge_failed")
    ).all()
    assert len(audits) == 1


def test_setup_requires_auth(client) -> None:
    resp = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": "x"})
    assert resp.status_code == 401


def test_setup_requires_csrf(client, db_session, logged_in_admin) -> None:
    resp = client.post("/api/auth/totp/setup")
    assert resp.status_code == 403


def test_totp_status_reflects_pending_enrollment(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token})
    status = client.get("/api/auth/totp/status").json
    assert status["enabled"] is False
    assert status["pending_enrollment"] is True


def test_secret_is_encrypted_at_rest(client, db_session, logged_in_admin, csrf_token) -> None:
    bundle = client.post("/api/auth/totp/setup", headers={"X-CSRF-Token": csrf_token}).json
    plaintext_secret = bundle["secret"]

    row = db_session.scalar(select(UserTotp).where(UserTotp.user_id == logged_in_admin.id))
    assert row is not None
    # Ciphertext must NOT contain the plaintext secret bytes
    assert plaintext_secret.encode("ascii") not in row.secret_ciphertext
    # Decryption via the service round-trips
    assert totp._decrypt_secret(row) == plaintext_secret  # type: ignore[attr-defined]
