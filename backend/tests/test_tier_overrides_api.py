"""Phase 10 — tier-override workflow tests.

Covers:
  - Owner creates a request when current classification exists
  - 409 on duplicate pending request
  - Same-tier request → 400
  - No-classification → 409
  - Admin lists pending
  - Admin approves → inserts new Classification row, latest tier flips
  - Admin denies → status flips to denied, classification unchanged
  - Approve/deny on already-decided → 409
  - Admin-only gating
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.tier_override import OverrideStatus, TierOverrideRequest
from app.services import classification as classification_service


def _upload(client, csrf_token, filename, content):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, "text/plain")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _classify(db_session, file_id, tier=ClassificationTier.CONFIDENTIAL):
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
    existing.categories_triggered = []
    existing.classifier_version = "v6"
    existing.classified_at = datetime.now(UTC)
    db_session.commit()
    return existing


def _create(client, csrf_token, file_id, tier, just="please reclassify"):
    return client.post(
        f"/api/files/{file_id}/tier-override-requests",
        json={"requested_tier": tier, "justification": just},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )


# --- Owner: create request ---


def test_owner_creates_request(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)

    resp = _create(client, csrf_token, file_id, "internal", "downgrade rationale")
    assert resp.status_code == 201, resp.data
    body = resp.json
    assert body["status"] == "pending"
    assert body["current_tier"] == "confidential"
    assert body["requested_tier"] == "internal"
    assert body["justification"] == "downgrade rationale"

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "tier_override.requested")
    ).all()
    assert len(audits) == 1


def test_create_without_classification_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    resp = _create(client, csrf_token, up.json["id"], "internal")
    assert resp.status_code == 409
    assert resp.json["error"] == "classification_pending"


def test_same_tier_request_is_400(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.INTERNAL)
    resp = _create(client, csrf_token, file_id, "internal")
    assert resp.status_code == 400
    assert resp.json["error"] == "same_tier"


def test_duplicate_pending_request_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    _create(client, csrf_token, file_id, "internal")
    dup = _create(client, csrf_token, file_id, "public")
    assert dup.status_code == 409
    assert dup.json["error"] == "already_pending"


def test_blank_justification_rejected(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    resp = _create(client, csrf_token, file_id, "internal", "   ")
    # Pydantic catches whitespace-only via min_length=1? Actually min_length on
    # the str checks length BEFORE strip — "   " has len 3 → passes pydantic →
    # caught by service-layer .strip() == "" path → 400 invalid_request.
    assert resp.status_code in (400, 422)


# --- Owner: cannot file on someone else's file ---


def test_non_owner_cannot_create(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    from app.models.file import File

    f = File(
        owner_id=seeded_admin.id,
        original_filename="notmine.txt",
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

    resp = _create(client, csrf_token, f.id, "internal")
    assert resp.status_code == 404


# --- Admin: list / approve / deny ---


def test_admin_lists_pending(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    _create(client, csrf_token, file_id, "internal", "looser please")

    resp = client.get("/api/admin/tier-override-requests")
    assert resp.status_code == 200
    items = resp.json["items"]
    assert len(items) == 1
    assert items[0]["status"] == "pending"


def test_admin_approve_flips_latest_classification(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    req = _create(client, csrf_token, file_id, "internal", "downgrade").json

    approve = client.post(
        f"/api/admin/tier-override-requests/{req['id']}/approve",
        json={"decision_reason": "approved after review"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert approve.status_code == 200
    assert approve.json["status"] == "approved"
    assert approve.json["reviewed_by_email"]

    # Latest classification is now INTERNAL with classifier_version='manual:override'
    latest = classification_service.get_latest(file_id)
    assert latest is not None
    assert latest.final_tier == ClassificationTier.INTERNAL
    assert latest.classifier_version == "manual:override"
    assert latest.version == 2

    # Original auto-tier row still exists
    rows = db_session.scalars(
        select(Classification).where(Classification.file_id == file_id)
    ).all()
    assert len(rows) == 2
    assert {r.final_tier for r in rows} == {
        ClassificationTier.CONFIDENTIAL,
        ClassificationTier.INTERNAL,
    }

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "tier_override.approved")
    ).all()
    assert len(audits) == 1
    assert audits[0].severity.value == "warning"


def test_admin_deny_keeps_classification(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    req = _create(client, csrf_token, file_id, "internal").json

    deny = client.post(
        f"/api/admin/tier-override-requests/{req['id']}/deny",
        json={"decision_reason": "rationale insufficient"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert deny.status_code == 200
    assert deny.json["status"] == "denied"
    assert deny.json["decision_reason"] == "rationale insufficient"

    # Classification unchanged
    rows = db_session.scalars(
        select(Classification).where(Classification.file_id == file_id)
    ).all()
    assert len(rows) == 1
    assert rows[0].final_tier == ClassificationTier.CONFIDENTIAL

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "tier_override.denied")
    ).all()
    assert len(audits) == 1


def test_approve_already_decided_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    req = _create(client, csrf_token, file_id, "internal").json
    client.post(
        f"/api/admin/tier-override-requests/{req['id']}/approve",
        json={},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    second = client.post(
        f"/api/admin/tier-override-requests/{req['id']}/approve",
        json={},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert second.status_code == 409
    assert second.json["error"] == "not_pending"


def test_admin_endpoints_require_admin(
    client, db_session, logged_in_user, csrf_token
) -> None:
    resp = client.get("/api/admin/tier-override-requests")
    assert resp.status_code == 403

    resp = client.post(
        f"/api/admin/tier-override-requests/{uuid.uuid4()}/approve",
        json={},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_admin_can_filter_by_status(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    req = _create(client, csrf_token, file_id, "internal").json
    client.post(
        f"/api/admin/tier-override-requests/{req['id']}/deny",
        json={"decision_reason": "no"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    pending = client.get("/api/admin/tier-override-requests?status=pending").json
    assert pending["items"] == []
    denied = client.get("/api/admin/tier-override-requests?status=denied").json
    assert len(denied["items"]) == 1
    all_ = client.get("/api/admin/tier-override-requests?status=all").json
    assert len(all_["items"]) == 1


# --- After approval, a new request can be filed ---


def test_after_approval_new_pending_allowed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    first = _create(client, csrf_token, file_id, "internal").json
    client.post(
        f"/api/admin/tier-override-requests/{first['id']}/approve",
        json={},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    # Tier is now INTERNAL; a fresh request to drop to PUBLIC should work
    second = _create(client, csrf_token, file_id, "public", "lower again")
    assert second.status_code == 201


# --- Owner can see their own file's request history ---


def test_owner_lists_history(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.CONFIDENTIAL)
    _create(client, csrf_token, file_id, "internal")

    resp = client.get(f"/api/files/{file_id}/tier-override-requests")
    assert resp.status_code == 200
    rows = db_session.scalars(select(TierOverrideRequest)).all()
    assert len(rows) == 1
    assert rows[0].status == OverrideStatus.PENDING
    assert len(resp.json["items"]) == 1
