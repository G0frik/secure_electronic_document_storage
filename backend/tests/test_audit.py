"""Tests for the audit service."""

from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditLog, AuditSeverity
from app.services import audit


def test_record_writes_row(db_session) -> None:
    entry = audit.record(
        "test.event",
        actor_ip="10.0.0.1",
        metadata={"foo": "bar"},
    )
    db_session.refresh(entry)

    assert entry.id is not None
    assert entry.action_type == "test.event"
    assert entry.actor_ip == "10.0.0.1"
    assert entry.event_metadata == {"foo": "bar"}
    assert entry.severity == AuditSeverity.INFO

    rows = db_session.scalars(select(AuditLog)).all()
    assert len(rows) == 1


def test_record_with_actor(db_session, seeded_admin) -> None:
    entry = audit.record(
        "user.created",
        actor=seeded_admin,
        target_type="user",
        target_id=seeded_admin.id,
        severity=AuditSeverity.WARNING,
    )
    db_session.refresh(entry)
    assert entry.actor_user_id == seeded_admin.id
    assert entry.severity == AuditSeverity.WARNING
