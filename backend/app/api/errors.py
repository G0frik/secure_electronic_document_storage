"""Central JSON error handlers."""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app.logging_config import get_logger
from app.services.auth import AuthError
from app.services.passwords import WeakPasswordError
from app.services.users import UserAlreadyExistsError

log = get_logger(__name__)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(WeakPasswordError)
    def handle_weak_password(exc: WeakPasswordError):  # type: ignore[no-untyped-def]
        return jsonify({"error": "weak_password", "code": exc.code, "message": str(exc)}), 422

    @app.errorhandler(UserAlreadyExistsError)
    def handle_duplicate_user(exc: UserAlreadyExistsError):  # type: ignore[no-untyped-def]
        return jsonify({"error": "user_exists", "message": str(exc)}), 409

    @app.errorhandler(AuthError)
    def handle_auth_error(exc: AuthError):  # type: ignore[no-untyped-def]
        return jsonify({"error": "invalid_credentials", "message": "Invalid credentials."}), 401

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):  # type: ignore[no-untyped-def]
        return (
            jsonify(
                {
                    "error": exc.name.lower().replace(" ", "_"),
                    "message": exc.description,
                }
            ),
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):  # type: ignore[no-untyped-def]
        log.exception("unhandled_exception", error=str(exc))
        return jsonify({"error": "internal_error", "message": "Internal server error."}), 500
