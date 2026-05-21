"""Authentication service. Login/logout/session lifecycle."""

from __future__ import annotations

import secrets
import uuid

from flask import g, session

from app.models.user import User, UserStatus
from app.services import audit, passwords, totp, users
from app.services.audit import AuditSeverity

# Real Argon2id hash of a random throwaway secret. Used to keep the timing of
# "unknown user" responses close to that of "wrong password" — verify_password
# still does full Argon2 work even though no real password can match this hash.
_DUMMY_HASH = passwords.hash_password(secrets.token_urlsafe(32))

# Session key used between password-step and TOTP-step of a 2FA login.
_PENDING_TOTP_KEY = "pending_totp_user_id"


class AuthError(Exception):
    """Raised by authenticate() on any failure (generic, no enumeration)."""


def authenticate(email: str, password: str) -> User:
    """Look up the user, verify password, return the User. Audit on every outcome."""
    user = users.get_user_by_email(email)

    # Verify even on user-not-found to keep timing roughly constant
    if user is None:
        passwords.verify_password(password, _DUMMY_HASH)
        audit.record(
            "auth.login.failure",
            metadata={"email": email.strip().lower(), "reason": "unknown_user"},
            severity=AuditSeverity.WARNING,
        )
        raise AuthError("Invalid credentials.")

    if not passwords.verify_password(password, user.password_hash):
        audit.record(
            "auth.login.failure",
            metadata={"email": user.email, "reason": "bad_password"},
            severity=AuditSeverity.WARNING,
            target_type="user",
            target_id=user.id,
        )
        raise AuthError("Invalid credentials.")

    if user.status != UserStatus.ACTIVE:
        audit.record(
            "auth.login.failure",
            actor=user,
            metadata={"email": user.email, "reason": f"status_{user.status.value}"},
            severity=AuditSeverity.WARNING,
            target_type="user",
            target_id=user.id,
        )
        raise AuthError("Invalid credentials.")

    return user


def requires_totp(user: User) -> bool:
    """Phase 6 — does this user have TOTP 2FA enabled?"""
    return totp.is_enabled(user)


def start_pending_totp(user: User) -> None:
    """Password-step succeeded but 2FA is enabled: mark the session as
    half-authenticated. The user can read /csrf and POST /totp/challenge
    but cannot reach any @login_required endpoint until they finish 2FA.
    """
    session[_PENDING_TOTP_KEY] = str(user.id)
    session.pop("user_id", None)
    session.permanent = True
    session.modified = True
    # Invalidate any cached current_user from earlier requests in the same
    # app context (Flask test client + db_session share `g` across requests).
    g.pop("current_user", None)
    audit.record(
        "auth.totp.challenge_issued",
        actor=user,
        target_type="user",
        target_id=user.id,
        metadata={"email": user.email},
    )


def pending_totp_user_id() -> uuid.UUID | None:
    raw = session.get(_PENDING_TOTP_KEY)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except (TypeError, ValueError):
        session.pop(_PENDING_TOTP_KEY, None)
        return None


def clear_pending_totp() -> None:
    session.pop(_PENDING_TOTP_KEY, None)


def start_session(user: User) -> None:
    """Mark the Flask session as authenticated for *user*.

    NOTE: we do NOT call session.clear() — that would wipe the CSRF token and
    break the next mutating request. session.clear() also does not rotate the
    session ID, so it provides no real session-fixation defense. Proper
    session-ID rotation is a deferred concern (see threat model).
    """
    from datetime import datetime, timezone

    session.pop(_PENDING_TOTP_KEY, None)
    session["user_id"] = str(user.id)
    # Phase 13 — issued_at is the timestamp the admin force-logout check
    # compares against `user.session_invalid_before` on every authenticated
    # request. Sessions older than that bump get cleared.
    session["issued_at"] = datetime.now(timezone.utc).isoformat()
    session.permanent = True
    session.modified = True
    # Invalidate any cached current_user from earlier requests in the same
    # app context (Flask test client + db_session share `g` across requests).
    g.pop("current_user", None)
    users.update_last_login(user)
    audit.record(
        "auth.login.success",
        actor=user,
        target_type="user",
        target_id=user.id,
        metadata={"email": user.email, "two_factor": requires_totp(user)},
    )


def end_session(user: User | None) -> None:
    """Clear session and audit the logout."""
    if user is not None:
        audit.record(
            "auth.logout",
            actor=user,
            target_type="user",
            target_id=user.id,
            metadata={"email": user.email},
        )
    # Explicitly drop auth state; Flask-Session needs `modified=True` to persist.
    session.pop("user_id", None)
    session.pop("csrf_token", None)
    session.clear()
    session.modified = True
    # Drop cached current_user — otherwise any code path still inside the same
    # app context (notably: tests that share an app context across requests)
    # would still see the logged-in user.
    g.pop("current_user", None)
