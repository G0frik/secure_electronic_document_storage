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
    return entry
