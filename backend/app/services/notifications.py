"""Notification dispatcher + queries (Phase 11).

The dispatcher inspects an `AuditLog` row that was just written and
decides whether to create one or more `Notification` rows. Each
notification is a per-user in-app feed entry; the bell + dropdown in
the SPA read from here.

For severity=critical events the dispatcher also enqueues an email task
through Celery (Mailhog catches it in the dev stack).

Dispatch rules live in `_RULES` as a list of (predicate, builder) pairs.
Adding a new event type means adding one rule, not editing five sites.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditLog, AuditSeverity
from app.models.file import File
from app.models.notification import Notification
from app.models.share_link import ShareLink
from app.models.tier_override import TierOverrideRequest
from app.models.user import Role, User

log = get_logger(__name__)


# --- Notification builder ---


@dataclass(frozen=True)
class _NotifSpec:
    recipient_id: uuid.UUID
    title: str
    body: str | None = None


def _file_owner_id(file_id: uuid.UUID | None) -> uuid.UUID | None:
    if file_id is None:
        return None
    record = db.session.get(File, file_id)
    return record.owner_id if record is not None else None


def _override_requester_id(meta: dict) -> uuid.UUID | None:
    raw = meta.get("request_id")
    if not raw:
        return None
    try:
        req_id = uuid.UUID(raw)
    except (TypeError, ValueError):
        return None
    req = db.session.get(TierOverrideRequest, req_id)
    return req.requested_by_id if req is not None else None


def _share_link_creator_id(meta: dict) -> uuid.UUID | None:
    raw = meta.get("share_link_id")
    if not raw:
        return None
    try:
        link_id = uuid.UUID(raw)
    except (TypeError, ValueError):
        return None
    link = db.session.get(ShareLink, link_id)
    return link.created_by_id if link is not None else None


def _admin_ids() -> list[uuid.UUID]:
    return list(
        db.session.scalars(select(User.id).where(User.role == Role.ADMIN))
    )


# --- Dispatch rules ---


def _on_classification_restricted(row: AuditLog) -> list[_NotifSpec]:
    meta = row.event_metadata or {}
    if meta.get("final_tier") != "restricted":
        return []
    owner = _file_owner_id(row.target_id)
    if owner is None:
        return []
    return [
        _NotifSpec(
            recipient_id=owner,
            title="Your file was classified RESTRICTED",
            body=f"{meta.get('filename', 'A file')} — review your sharing.",
        )
    ]


def _on_share_link_used(row: AuditLog) -> list[_NotifSpec]:
    creator = _share_link_creator_id(row.event_metadata or {})
    if creator is None:
        return []
    meta = row.event_metadata or {}
    use_count = meta.get("use_count_after", "?")
    return [
        _NotifSpec(
            recipient_id=creator,
            title="External link downloaded",
            body=f"Use #{use_count} on a link you created.",
        )
    ]


def _on_share_received(row: AuditLog) -> list[_NotifSpec]:
    meta = row.event_metadata or {}
    raw = meta.get("recipient_id")
    if not raw:
        return []
    try:
        recipient_id = uuid.UUID(raw)
    except (TypeError, ValueError):
        return None  # type: ignore[return-value]
    return [
        _NotifSpec(
            recipient_id=recipient_id,
            title="A file was shared with you",
            body=f"{meta.get('permission', 'viewer')} access.",
        )
    ]


def _on_override_decision(title: str) -> Callable[[AuditLog], list[_NotifSpec]]:
    def handler(row: AuditLog) -> list[_NotifSpec]:
        meta = row.event_metadata or {}
        requester = _override_requester_id(meta)
        if requester is None:
            return []
        body_bits = [
            f"{meta.get('current_tier', '?')} → {meta.get('requested_tier', '?')}"
        ]
        if meta.get("decision_reason"):
            body_bits.append(str(meta["decision_reason"]))
        return [
            _NotifSpec(
                recipient_id=requester,
                title=title,
                body=" · ".join(body_bits),
            )
        ]

    return handler


def _on_override_requested_notify_admins(row: AuditLog) -> list[_NotifSpec]:
    meta = row.event_metadata or {}
    return [
        _NotifSpec(
            recipient_id=admin_id,
            title="Tier override request awaits review",
            body=(
                f"{meta.get('current_tier', '?')} → "
                f"{meta.get('requested_tier', '?')}"
            ),
        )
        for admin_id in _admin_ids()
    ]


# (action_type, builder)
_RULES: list[tuple[str, Callable[[AuditLog], list[_NotifSpec]]]] = [
    ("classification.completed", _on_classification_restricted),
    ("share_link.downloaded", _on_share_link_used),
    ("share.created", _on_share_received),
    ("tier_override.requested", _on_override_requested_notify_admins),
    ("tier_override.approved", _on_override_decision("Override approved")),
    ("tier_override.denied", _on_override_decision("Override denied")),
]


# --- Public API ---


def dispatch_for(row: AuditLog) -> list[Notification]:
    """Inspect *row* and create any notifications it implies. Returns the
    inserted Notification objects (mostly useful for tests).

    Notifications are committed immediately so the bell badge updates on
    the next poll without waiting for the originating transaction.
    """
    specs: list[_NotifSpec] = []
    for action_type, handler in _RULES:
        if row.action_type == action_type:
            try:
                specs.extend(handler(row) or [])
            except Exception as exc:  # noqa: BLE001 — never block the request
                log.warning(
                    "notifications.dispatch_failed",
                    action=row.action_type,
                    error=str(exc),
                )

    if not specs:
        return []

    created: list[Notification] = []
    severity = row.severity.value if hasattr(row.severity, "value") else str(row.severity)
    for spec in specs:
        n = Notification(
            recipient_user_id=spec.recipient_id,
            audit_log_id=row.id,
            action_type=row.action_type,
            title=spec.title,
            body=spec.body,
            severity=severity,
        )
        db.session.add(n)
        created.append(n)
    db.session.commit()

    # Critical-severity events ALSO get an email (Mailhog catches them in dev).
    if severity == AuditSeverity.CRITICAL.value:
        from app.tasks.notifications import send_email_for_notification

        for n in created:
            try:
                send_email_for_notification.delay(str(n.id))
            except Exception as exc:  # noqa: BLE001 — Celery down shouldn't break audit
                log.warning(
                    "notifications.email_enqueue_failed",
                    notification_id=str(n.id),
                    error=str(exc),
                )
    return created


# --- Read queries ---


def list_for_user(
    user: User, *, limit: int = 50, unread_only: bool = False
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.recipient_user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(db.session.scalars(stmt))


def unread_count(user: User) -> int:
    return (
        db.session.scalar(
            select(db.func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


def get_for_user(user: User, notification_id: uuid.UUID) -> Notification | None:
    return db.session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == user.id,
        )
    )


def mark_read(notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.session.commit()
    return notification


def mark_all_read(user: User) -> int:
    """Bulk mark every unread notification for *user* as read. Returns count."""
    now = datetime.now(timezone.utc)
    result = db.session.execute(
        Notification.__table__.update()
        .where(
            Notification.recipient_user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.session.commit()
    return result.rowcount or 0


def to_payload(notification: Notification) -> dict[str, Any]:
    return {
        "id": str(notification.id),
        "action_type": notification.action_type,
        "title": notification.title,
        "body": notification.body,
        "severity": notification.severity,
        "audit_log_id": (
            str(notification.audit_log_id) if notification.audit_log_id else None
        ),
        "read_at": (
            notification.read_at.isoformat() if notification.read_at else None
        ),
        "created_at": (
            notification.created_at.isoformat() if notification.created_at else None
        ),
    }
