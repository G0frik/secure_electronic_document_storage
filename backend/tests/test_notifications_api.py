"""Phase 11 — notification feed + admin events API tests."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.audit import AuditLog, AuditSeverity
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.notification import Notification
from app.services import audit


def _upload(client, csrf_token, filename, content):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, "text/plain")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _classify(db_session, file_id, tier, *, categories=None):
    existing = db_session.scalar(
        select(Classification).where(Classification.file_id == file_id)
    )
    if existing is None:
        existing = Classification(file_id=file_id, version=1)
        db_session.add(existing)
    existing.status = ClassificationStatus.COMPLETED
    existing.final_tier = tier
    existing.zero_shot_tier = tier
    existing.presidio_tier = ClassificationTier.PUBLIC
    existing.categories_triggered = categories or []
    existing.classifier_version = "v6"
    existing.classified_at = datetime.now(UTC)
    db_session.commit()
    return existing


# --- Notification dispatch (drives via audit.record + the wiring) ---


def test_classification_restricted_notifies_owner(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """When `classification.completed` audit fires with final_tier=restricted,
    the dispatcher creates a notification for the file's owner."""
    up = _upload(client, csrf_token, "x.txt", b"hi").json
    file_id = uuid.UUID(up["id"])

    # Emulate the worker's audit emit for a RESTRICTED classification.
    audit.record(
        "classification.completed",
        target_type="file",
        target_id=file_id,
        metadata={
            "final_tier": "restricted",
            "filename": "x.txt",
            "categories_triggered": ["personally identifiable information"],
        },
    )

    notifs = db_session.scalars(
        select(Notification).where(Notification.recipient_user_id == logged_in_admin.id)
    ).all()
    titles = [n.title for n in notifs]
    assert any("RESTRICTED" in t for t in titles)


def test_share_received_notifies_recipient(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    audit.record(
        "share.created",
        actor=logged_in_admin,
        target_type="file",
        target_id=uuid.uuid4(),
        metadata={
            "recipient_id": str(seeded_user.id),
            "permission": "viewer",
        },
    )
    notifs = db_session.scalars(
        select(Notification).where(Notification.recipient_user_id == seeded_user.id)
    ).all()
    assert len(notifs) == 1
    assert "shared with you" in notifs[0].title.lower()


def test_tier_override_notification_chain(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """End-to-end: user requests override → admin is notified; admin approves
    → requester is notified."""
    # Set up a file owned by alice with a CONFIDENTIAL classification.
    from app.models.file import File

    f = File(
        owner_id=seeded_user.id,
        original_filename="x.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(f)
    db_session.commit()
    _classify(db_session, f.id, ClassificationTier.CONFIDENTIAL)

    # Log in as alice, file the request
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    )
    req = client.post(
        f"/api/files/{f.id}/tier-override-requests",
        json={"requested_tier": "internal", "justification": "press release"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    ).json

    # Admins get notified
    admin_notifs = db_session.scalars(
        select(Notification).where(
            Notification.recipient_user_id == logged_in_admin.id,
            Notification.action_type == "tier_override.requested",
        )
    ).all()
    assert len(admin_notifs) == 1

    # Log in as admin, approve
    client.post("/api/auth/logout", headers={"X-CSRF-Token": new_csrf})
    admin_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": logged_in_admin.email, "password": "AdminPassword123!"},
        headers={"X-CSRF-Token": admin_csrf, "Content-Type": "application/json"},
    )
    approve = client.post(
        f"/api/admin/tier-override-requests/{req['id']}/approve",
        json={"decision_reason": "ok"},
        headers={"X-CSRF-Token": admin_csrf, "Content-Type": "application/json"},
    )
    assert approve.status_code == 200

    # Requester gets notified
    alice_notifs = db_session.scalars(
        select(Notification).where(
            Notification.recipient_user_id == seeded_user.id,
            Notification.action_type == "tier_override.approved",
        )
    ).all()
    assert len(alice_notifs) == 1
    assert "approved" in alice_notifs[0].title.lower()


# --- Notification API ---


def test_list_returns_own_notifications(client, db_session, logged_in_admin) -> None:
    audit.record(
        "share.created",
        actor=logged_in_admin,
        metadata={"recipient_id": str(logged_in_admin.id), "permission": "viewer"},
    )
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    assert resp.json["unread_count"] >= 1
    assert len(resp.json["items"]) >= 1


def test_unread_count_endpoint(client, db_session, logged_in_admin) -> None:
    audit.record(
        "share.created",
        actor=logged_in_admin,
        metadata={"recipient_id": str(logged_in_admin.id), "permission": "viewer"},
    )
    resp = client.get("/api/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.json["unread_count"] >= 1


def test_mark_read(client, db_session, logged_in_admin, csrf_token) -> None:
    audit.record(
        "share.created",
        actor=logged_in_admin,
        metadata={"recipient_id": str(logged_in_admin.id), "permission": "viewer"},
    )
    n = db_session.scalars(select(Notification)).first()
    resp = client.post(
        f"/api/notifications/{n.id}/read", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 200
    assert resp.json["read_at"] is not None
    db_session.refresh(n)
    assert n.read_at is not None


def test_mark_all_read(client, db_session, logged_in_admin, csrf_token) -> None:
    # Drop three notifications for the admin
    for _ in range(3):
        audit.record(
            "share.created",
            actor=logged_in_admin,
            metadata={
                "recipient_id": str(logged_in_admin.id),
                "permission": "viewer",
            },
        )
    resp = client.post(
        "/api/notifications/read-all", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 200
    assert resp.json["marked_read"] >= 3
    unread_after = client.get("/api/notifications/unread-count").json
    assert unread_after["unread_count"] == 0


def test_cant_read_someone_elses_notification(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """Notification owner check — 404 on someone else's row."""
    n = Notification(
        recipient_user_id=seeded_user.id,
        action_type="test.foo",
        title="not yours",
        body=None,
        severity="info",
    )
    db_session.add(n)
    db_session.commit()
    resp = client.post(
        f"/api/notifications/{n.id}/read", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 404


# --- Admin events API ---


def test_admin_events_returns_ecs_shape(
    client, db_session, logged_in_admin
) -> None:
    audit.record(
        "auth.login.success",
        actor=logged_in_admin,
        metadata={"email": logged_in_admin.email},
    )
    resp = client.get("/api/admin/events?action=auth.login.success")
    assert resp.status_code == 200
    body = resp.json
    assert body["count"] >= 1
    item = body["items"][0]
    assert item["event"]["action"] == "auth.login.success"
    assert item["event"]["category"] == ["authentication"]
    assert item["service"]["name"] == "docstore"
    assert item["@timestamp"]


def test_admin_events_filter_by_severity(
    client, db_session, logged_in_admin
) -> None:
    audit.record("test.warn", severity=AuditSeverity.WARNING)
    audit.record("test.info", severity=AuditSeverity.INFO)
    resp = client.get("/api/admin/events?severity=warning")
    actions = [item["event"]["action"] for item in resp.json["items"]]
    assert "test.warn" in actions
    assert "test.info" not in actions


def test_admin_events_requires_admin(client, db_session, logged_in_user) -> None:
    resp = client.get("/api/admin/events")
    assert resp.status_code == 403


def test_admin_events_rejects_bad_severity(
    client, db_session, logged_in_admin
) -> None:
    resp = client.get("/api/admin/events?severity=banana")
    assert resp.status_code == 400


# --- audit_log → notification linkage ---


def test_notification_references_audit_log(client, db_session, logged_in_admin) -> None:
    audit.record(
        "share.created",
        actor=logged_in_admin,
        metadata={
            "recipient_id": str(logged_in_admin.id),
            "permission": "viewer",
        },
    )
    n = db_session.scalars(
        select(Notification).where(Notification.recipient_user_id == logged_in_admin.id)
    ).first()
    assert n is not None
    assert n.audit_log_id is not None
    parent = db_session.scalar(
        select(AuditLog).where(AuditLog.id == n.audit_log_id)
    )
    assert parent is not None
    assert parent.action_type == "share.created"
