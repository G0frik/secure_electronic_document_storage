"""Authentication API blueprint."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, make_response, request
from pydantic import ValidationError

from app.config import settings
from app.extensions import limiter
from app.models.audit import AuditSeverity
from app.schemas.auth import LoginRequest, RegisterRequest, TotpCodeRequest
from app.services import audit, auth as auth_service
from app.services import csrf, passwords, totp, users
from app.services.totp import TotpError
from app.services.users import UserAlreadyExistsError
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_payload(user) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "status": user.status.value,
        "is_manager": user.is_manager,
        "department_id": str(user.department_id) if user.department_id else None,
        "department": user.department.name if user.department else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "two_factor_enabled": totp.is_enabled(user),
    }


@bp.get("/csrf")
def get_csrf_token():  # type: ignore[no-untyped-def]
    """Return a CSRF token; also set it in a JS-readable cookie for the SPA."""
    token = csrf.get_or_create_token()
    response = make_response(jsonify({"csrf_token": token}))
    response.set_cookie(
        csrf._COOKIE_NAME,
        token,
        httponly=False,  # SPA reads it back via JS
        samesite="Lax",
        secure=not settings.is_development,
        path="/",
    )
    return response


@bp.post("/login")
@limiter.limit("5 per minute")
@csrf.csrf_protect
def login():  # type: ignore[no-untyped-def]
    try:
        payload = LoginRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    user = auth_service.authenticate(payload.email, payload.password)

    # Phase 6: if the user has TOTP enabled, don't start the full session yet.
    if auth_service.requires_totp(user):
        auth_service.start_pending_totp(user)
        return jsonify({"requires_totp": True}), 200

    auth_service.start_session(user)
    return jsonify(_user_payload(user)), 200


@bp.post("/totp/challenge")
@limiter.limit("5 per minute")
@csrf.csrf_protect
def totp_challenge():  # type: ignore[no-untyped-def]
    """Step 2 of the 2FA login. Reads the half-authenticated session set by
    /login, verifies the supplied TOTP (or recovery) code, and promotes the
    session to fully authenticated.
    """
    pending_id = auth_service.pending_totp_user_id()
    if pending_id is None:
        abort(401, description="No pending TOTP challenge.")

    try:
        payload = TotpCodeRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    user = users.get_user_by_id(pending_id)
    if user is None or not user.is_active:
        auth_service.clear_pending_totp()
        abort(401, description="User no longer active.")

    if not totp.verify_for_login(user, payload.code):
        audit.record(
            "auth.totp.challenge_failed",
            actor=user,
            target_type="user",
            target_id=user.id,
            metadata={"email": user.email},
            severity=AuditSeverity.WARNING,
        )
        abort(401, description="Invalid TOTP or recovery code.")

    auth_service.start_session(user)
    audit.record(
        "auth.totp.challenge_passed",
        actor=user,
        target_type="user",
        target_id=user.id,
        metadata={"email": user.email},
        severity=AuditSeverity.INFO,
    )
    return jsonify(_user_payload(user)), 200


@bp.post("/logout")
@csrf.csrf_protect
def logout():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    auth_service.end_session(user)
    return jsonify({"status": "ok"}), 200


@bp.get("/me")
@login_required
def me():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    return jsonify(_user_payload(user)), 200


@bp.post("/register")
@limiter.limit("3 per minute")
@csrf.csrf_protect
def register():  # type: ignore[no-untyped-def]
    """Open in dev; admin-only in prod.

    Mode is controlled by `settings.registration_open_to_public`.
    """
    actor = current_user_or_none()

    if not settings.registration_open_to_public:
        # In prod (or when explicitly disabled): require admin.
        if actor is None:
            abort(401, description="Authentication required.")
        if not actor.is_admin:
            abort(403, description="Admin role required.")

    try:
        payload = RegisterRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    passwords.validate_password_policy(payload.password)

    try:
        user = users.create_user(
            email=payload.email,
            password=payload.password,
            role=payload.role,
            department_id=payload.department_id,
            is_manager=payload.is_manager,
            actor=actor,
        )
    except UserAlreadyExistsError:
        raise

    return jsonify(_user_payload(user)), 201


# --- Phase 6 — TOTP enrollment ---


@bp.get("/totp/status")
@login_required
def totp_status():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    row = totp.get_for_user(user)
    return (
        jsonify(
            {
                "enabled": bool(row and row.enabled),
                "pending_enrollment": bool(row and not row.enabled),
                "remaining_recovery_codes": (
                    totp.remaining_recovery_codes(row) if row else 0
                ),
                "last_used_at": (
                    row.last_used_at.isoformat()
                    if row and row.last_used_at
                    else None
                ),
            }
        ),
        200,
    )


@bp.post("/totp/setup")
@login_required
@csrf.csrf_protect
def totp_setup():  # type: ignore[no-untyped-def]
    """Begin enrollment. Returns the otpauth URI + plaintext recovery codes.
    The user MUST run /totp/verify with a code from their app to finish.
    """
    user = current_user_or_none()
    try:
        bundle = totp.setup_for_user(user)
    except TotpError as exc:
        return jsonify({"error": "totp_setup_failed", "message": str(exc)}), 409

    audit.record(
        "auth.totp.setup_started",
        actor=user,
        target_type="user",
        target_id=user.id,
        metadata={"email": user.email},
        severity=AuditSeverity.INFO,
    )
    return (
        jsonify(
            {
                "otpauth_uri": bundle.otpauth_uri,
                "secret": bundle.secret_b32,
                "recovery_codes": bundle.recovery_codes,
            }
        ),
        201,
    )


@bp.post("/totp/verify")
@login_required
@csrf.csrf_protect
def totp_verify():  # type: ignore[no-untyped-def]
    """Confirm enrollment by submitting a fresh code from the authenticator app."""
    user = current_user_or_none()
    try:
        payload = TotpCodeRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        totp.enable_for_user(user, payload.code)
    except TotpError as exc:
        return jsonify({"error": "totp_verify_failed", "message": str(exc)}), 400

    audit.record(
        "auth.totp.enabled",
        actor=user,
        target_type="user",
        target_id=user.id,
        metadata={"email": user.email},
        severity=AuditSeverity.INFO,
    )
    return jsonify({"enabled": True}), 200


@bp.post("/totp/disable")
@login_required
@csrf.csrf_protect
def totp_disable():  # type: ignore[no-untyped-def]
    """Tear down 2FA. Requires a fresh TOTP or recovery code."""
    user = current_user_or_none()
    try:
        payload = TotpCodeRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        totp.disable_for_user(user, payload.code)
    except TotpError as exc:
        return jsonify({"error": "totp_disable_failed", "message": str(exc)}), 400

    audit.record(
        "auth.totp.disabled",
        actor=user,
        target_type="user",
        target_id=user.id,
        metadata={"email": user.email},
        severity=AuditSeverity.WARNING,
    )
    return jsonify({"enabled": False}), 200
