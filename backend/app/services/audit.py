"""Central audit logging service.

Every state-changing service MUST call `record()` after a successful write.
"""

from __future__ import annotations

import uuid
from typing import Any

from flask import has_request_context, request

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditLog, AuditSeverity
from app.models.user import User

log = get_logger(__name__)


def _current_ip() -> str | None:
    if not has_request_context():
        return None
    # NOTE: behind a reverse proxy, prefer request.access_route[0] / X-Forwarded-For
    # after configuring ProxyFix.
    return request.remote_addr


def record(
    action_type: str,
    *,
    actor: User | None = None,
    actor_ip: str | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    severity: AuditSeverity = AuditSeverity.INFO,
    commit: bool = True,
) -> AuditLog:
    """Insert one audit row. Returns the created object.

    Caller is responsible for committing only if `commit=False`.
    """
    entry = AuditLog(
        actor_user_id=actor.id if actor is not None else None,
        actor_ip=actor_ip if actor_ip is not None else _current_ip(),
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        event_metadata=metadata,
        severity=severity,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()

    log.info(
        "audit.record",
        action_type=action_type,
        actor_user_id=str(actor.id) if actor else None,
        actor_ip=entry.actor_ip,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
        severity=severity.value,
    )

    # Phase 11 — SIEM-friendly NDJSON sink + in-app notifications.
    # Deferred imports keep `audit.py` free of the dispatch + ECS deps
    # (which would otherwise drag the file-rotation logger into every test).
    #
    # We fire regardless of the `commit` flag: many service-layer callers
    # use `commit=False` to batch the audit row with their own DB writes,
    # so a `commit`-gated hook would silently drop notifications for
    # half the call sites. `dispatch_for` runs its own commit, which
    # also flushes the parent's pending session — atomically committing
    # the audit row + the parent's domain rows + the notifications.
    try:
        from app.services import events, notifications

        events.emit(entry)
        notifications.dispatch_for(entry)
    except Exception as exc:  # noqa: BLE001 — never let stream sinks block audit
        log.warning(
            "audit.stream_sink_failed",
            action_type=action_type,
            error=str(exc),
        )
    return entry
