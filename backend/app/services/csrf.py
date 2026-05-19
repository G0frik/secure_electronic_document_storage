"""CSRF protection via double-submit cookie pattern.

GET /api/auth/csrf returns a token AND sets it in a non-httpOnly cookie. The SPA
echoes the token back in the `X-CSRF-Token` header on every mutating request.
Server compares the header against the session-bound token.
"""

from __future__ import annotations

import functools
import secrets
from collections.abc import Callable
from typing import Any

from flask import abort, request, session

_SESSION_KEY = "csrf_token"
_HEADER_NAME = "X-CSRF-Token"
_COOKIE_NAME = "csrf_token"
_TOKEN_BYTES = 32


def get_or_create_token() -> str:
    """Return the current session's CSRF token, creating one if absent."""
    token = session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        session[_SESSION_KEY] = token
    return token


def validate(header_value: str | None) -> bool:
    """Constant-time compare header value to session token."""
    expected = session.get(_SESSION_KEY)
    if not expected or not header_value:
        return False
    return secrets.compare_digest(expected, header_value)


def csrf_protect(view: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: enforce CSRF on mutating endpoints. Returns 403 if missing/invalid."""

    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not validate(request.headers.get(_HEADER_NAME)):
            abort(403, description="Invalid or missing CSRF token.")
        return view(*args, **kwargs)

    return wrapped


__all__ = ["csrf_protect", "get_or_create_token", "validate", "_COOKIE_NAME", "_HEADER_NAME"]
