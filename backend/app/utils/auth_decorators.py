"""Auth decorators for route handlers."""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any

from flask import abort, g, session

from app.services.users import get_user_by_id


def _load_current_user() -> None:
    """Populate g.current_user from the session, if logged in."""
    if "current_user" in g:
        return
    raw_id = session.get("user_id")
    if not raw_id:
        g.current_user = None
        return
    try:
        user_id = uuid.UUID(raw_id)
    except (TypeError, ValueError):
        session.clear()
        g.current_user = None
        return
    user = get_user_by_id(user_id)
    if user is None or not user.is_active:
        session.clear()
        g.current_user = None
        return
    g.current_user = user


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        _load_current_user()
        if g.current_user is None:
            abort(401, description="Authentication required.")
        return view(*args, **kwargs)

    return wrapped


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        _load_current_user()
        if g.current_user is None:
            abort(401, description="Authentication required.")
        if not g.current_user.is_admin:
            abort(403, description="Admin role required.")
        return view(*args, **kwargs)

    return wrapped


def current_user_or_none() -> Any:
    _load_current_user()
    return g.current_user
