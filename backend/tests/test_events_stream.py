"""Phase 11 — ECS mapping + NDJSON sink unit tests.

These don't touch the rotating file logger directly (settings disable it
in tests); we exercise the `to_ecs` mapper + a manual NDJSON write into
a tmp_path so the test stays hermetic.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.config import settings
from app.models.audit import AuditLog, AuditSeverity
from app.services import audit, events


def _make_row(action_type: str, **kwargs) -> AuditLog:
    return AuditLog(
        id=kwargs.pop("id", uuid.uuid4()),
        timestamp=kwargs.pop("timestamp", datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)),
        actor_user_id=kwargs.pop("actor_user_id", None),
        actor_ip=kwargs.pop("actor_ip", None),
        action_type=action_type,
        target_type=kwargs.pop("target_type", None),
        target_id=kwargs.pop("target_id", None),
        event_metadata=kwargs.pop("event_metadata", None),
        severity=kwargs.pop("severity", AuditSeverity.INFO),
    )


def test_ecs_basic_shape() -> None:
    row = _make_row(
        "auth.login.success",
        actor_user_id=uuid.uuid4(),
        actor_ip="10.0.0.5",
        event_metadata={"email": "alice@example.com"},
    )
    payload = events.to_ecs(row)

    # Top-level ECS fields are present and well-formed
    assert payload["@timestamp"] == "2026-05-20T12:00:00+00:00"
    assert payload["event"]["action"] == "auth.login.success"
    assert payload["event"]["kind"] == "event"
    assert payload["event"]["category"] == ["authentication"]
    assert payload["event"]["type"] == ["start"]
    assert payload["event"]["outcome"] == "success"
    assert payload["event"]["severity"] == 20
    assert payload["event"]["dataset"] == "docstore.audit"
    assert payload["service"]["name"] == "docstore"
    assert payload["log"]["level"] == "info"
    assert payload["source"]["ip"] == "10.0.0.5"
    assert payload["user"]["email"] == "alice@example.com"
    assert "logged in" in payload["message"]


def test_ecs_failure_outcome() -> None:
    row = _make_row(
        "auth.login.failure",
        event_metadata={"reason": "bad_password", "email": "alice@example.com"},
        severity=AuditSeverity.WARNING,
    )
    payload = events.to_ecs(row)
    assert payload["event"]["outcome"] == "failure"
    assert payload["event"]["severity"] == 50  # warning


def test_ecs_file_block_is_populated() -> None:
    row = _make_row(
        "file.uploaded",
        target_type="file",
        target_id=uuid.uuid4(),
        event_metadata={
            "filename": "salary.pdf",
            "size_bytes": 1234,
            "mime_type": "application/pdf",
            "sha256": "f" * 64,
        },
    )
    payload = events.to_ecs(row)
    assert payload["file"]["name"] == "salary.pdf"
    assert payload["file"]["size"] == 1234
    assert payload["file"]["mime_type"] == "application/pdf"
    assert payload["file"]["hash"]["sha256"] == "f" * 64
    # ECS-lifted fields don't double up in labels.metadata
    assert "filename" not in payload["labels"].get("metadata", {})


def test_ecs_share_link_use_denied_is_failure() -> None:
    row = _make_row(
        "share_link.use_denied",
        event_metadata={"reason": "expired"},
        severity=AuditSeverity.WARNING,
    )
    payload = events.to_ecs(row)
    assert payload["event"]["outcome"] == "failure"
    assert payload["labels"]["metadata"] == {"reason": "expired"}


def test_ndjson_round_trip(tmp_path) -> None:
    """Wire the file sink at a tmp path and verify the JSON line is parseable."""
    original = settings.event_log_path
    try:
        settings.event_log_path = str(tmp_path / "events.jsonl")
        events._reset_file_sink_for_tests()  # noqa: SLF001
        row = _make_row(
            "file.downloaded",
            target_type="file",
            target_id=uuid.uuid4(),
            event_metadata={"filename": "report.txt", "size_bytes": 42},
        )
        events.emit(row)
        contents = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(contents) == 1
        parsed = json.loads(contents[0])
        assert parsed["event"]["action"] == "file.downloaded"
        assert parsed["file"]["name"] == "report.txt"
    finally:
        settings.event_log_path = original
        events._reset_file_sink_for_tests()  # noqa: SLF001


def test_audit_record_emits_to_stream(client, db_session, logged_in_admin) -> None:
    """End-to-end: audit.record → events.emit. We don't write to the real file
    in tests (settings.event_log_path = ""); just verify the function chain
    runs without exceptions for a typical request."""
    entry = audit.record(
        "test.smoke",
        actor=logged_in_admin,
        target_type="user",
        target_id=logged_in_admin.id,
        metadata={"hello": "world"},
        severity=AuditSeverity.INFO,
    )
    assert entry.id is not None
    payload = events.to_ecs(entry)
    assert payload["event"]["action"] == "test.smoke"
    assert payload["labels"]["metadata"] == {"hello": "world"}
