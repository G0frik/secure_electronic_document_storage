"""Authentication API blueprint."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, make_response, request
from pydantic import ValidationError

from app.config import settings
from app.extensions import limiter
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import auth as auth_service
from app.services import csrf, passwords, users
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
    auth_service.start_session(user)
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
