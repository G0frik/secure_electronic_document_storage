"""User-facing notifications API (Phase 11).

  GET    /api/notifications        — recent feed (+ ?unread=true)
  GET    /api/notifications/unread-count — bell badge
  POST   /api/notifications/<id>/read    — mark one read
  POST   /api/notifications/read-all     — mark every unread as read
"""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request

from app.services import csrf, notifications
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


@bp.get("")
@login_required
def list_notifications():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    unread = request.args.get("unread", "").lower() in {"1", "true", "yes"}
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
    except ValueError:
        limit = 50
    items = notifications.list_for_user(user, limit=limit, unread_only=unread)
    return (
        jsonify(
            {
                "items": [notifications.to_payload(n) for n in items],
                "unread_count": notifications.unread_count(user),
            }
        ),
        200,
    )


@bp.get("/unread-count")
@login_required
def unread_count():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    return jsonify({"unread_count": notifications.unread_count(user)}), 200


@bp.post("/<uuid:notification_id>/read")
@login_required
@csrf.csrf_protect
def mark_read(notification_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    n = notifications.get_for_user(user, notification_id)
    if n is None:
        abort(404, description="Notification not found.")
    notifications.mark_read(n)
    return jsonify(notifications.to_payload(n)), 200


@bp.post("/read-all")
@login_required
@csrf.csrf_protect
def mark_all_read():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    count = notifications.mark_all_read(user)
    return jsonify({"marked_read": count}), 200
