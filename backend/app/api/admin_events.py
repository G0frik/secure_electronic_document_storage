"""Admin-only events API (Phase 11). Returns ECS-shaped JSON over the
audit log — same format the NDJSON sink writes. This is the "pull" path
for SIEMs that prefer polling an HTTP endpoint over tailing a file.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from app.extensions import db
from app.models.audit import AuditLog, AuditSeverity
from app.services import events
from app.utils.auth_decorators import admin_required

bp = Blueprint("admin_events", __name__, url_prefix="/api/admin/events")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # `fromisoformat` accepts the "Z" suffix from 3.11+; we're on 3.12.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@bp.get("")
@admin_required
def list_events():  # type: ignore[no-untyped-def]
    """Query the event stream in ECS-shaped JSON.

    Query params:
      since=<iso-8601>    — events at-or-after this timestamp
      until=<iso-8601>    — events at-or-before this timestamp
      action=<dotted>     — exact match on event.action
      severity=info|warning|critical
      limit=<int>         — default 100, max 1000
    """
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc())

    since = _parse_iso(request.args.get("since"))
    until = _parse_iso(request.args.get("until"))
    if since is not None:
        stmt = stmt.where(AuditLog.timestamp >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.timestamp <= until)

    action = request.args.get("action")
    if action:
        stmt = stmt.where(AuditLog.action_type == action)

    severity = (request.args.get("severity") or "").lower()
    if severity:
        try:
            stmt = stmt.where(AuditLog.severity == AuditSeverity(severity))
        except ValueError:
            return jsonify({"error": "invalid_request", "message": "Bad severity."}), 400

    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 1000))
    except ValueError:
        limit = 100
    stmt = stmt.limit(limit)

    rows = list(db.session.scalars(stmt))
    return (
        jsonify(
            {
                "items": [events.to_ecs(r) for r in rows],
                "count": len(rows),
                "limit": limit,
                "queried_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        200,
    )
