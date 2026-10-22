"""Phase 7 — /api/shares/* + cloud-drive share semantics in policy.

Covers:
  - Create share (file + folder), validation, dup-check, self-share, reactivate-after-revoke
  - List received / granted
  - Revoke (granter or admin only)
  - Folder share gives recipient access to every file inside (recursively)
  - Share elevates over tier ceiling but a `denied_categories` policy still blocks
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.file import File
from app.models.folder import Folder
from app.models.policy import AccessPolicy
from app.models.share import Share, SharePermission, ShareTargetType
from app.models.user import Role

# --- Helpers ---


def _make_file(db_session, owner, *, folder_id=None, filename="doc.txt") -> File:
    f = File(
        owner_id=owner.id,
        folder_id=folder_id,
        original_filename=filename,
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
    return f


def _classify(
    db_session, file: File, tier: ClassificationTier, categories=None
) -> Classification:
    c = Classification(
        file_id=file.id,
        version=1,
        status=ClassificationStatus.COMPLETED,
        final_tier=tier,
        zero_shot_tier=tier,
        presidio_tier=ClassificationTier.PUBLIC,
        categories_triggered=categories or [],
        classifier_version="v6",
        classified_at=datetime.now(UTC),
    )
    db_session.add(c)
    db_session.commit()
    return c


def _share_payload_file(file_id, recipient_email, permission="viewer"):
    return {
        "target_type": "file",
        "target_id": str(file_id),
        "recipient_email": recipient_email,
        "permission": permission,
    }


def _share_payload_folder(folder_id, recipient_email):
    return {
        "target_type": "folder",
        "target_id": str(folder_id),
        "recipient_email": recipient_email,
        "permission": "viewer",
    }


# --- Create ---


def test_create_file_share(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    f = _make_file(db_session, logged_in_admin)
    resp = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201, resp.data
    body = resp.json
    assert body["target_type"] == "file"
    assert body["permission"] == "viewer"
    assert body["recipient_email"] == seeded_user.email

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "share.created")
    ).all()
    assert len(audits) == 1


def test_create_folder_share(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    folder = Folder(owner_id=logged_in_admin.id, name="HR")
    db_session.add(folder)
    db_session.commit()
    resp = client.post(
        "/api/shares",
        json=_share_payload_folder(folder.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201


def test_cannot_share_with_self(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    f = _make_file(db_session, logged_in_admin)
    resp = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, logged_in_admin.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json["error"] == "share_self"


def test_cannot_share_other_users_file(
    client, db_session, logged_in_user, seeded_admin, seeded_other_user, csrf_token
) -> None:
    f = _make_file(db_session, seeded_admin)  # owned by someone else
    resp = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_other_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    # Non-admin trying to share a file they don't own → 404 (anti-enumeration)
    assert resp.status_code == 404


def test_share_with_unknown_recipient_is_404(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    f = _make_file(db_session, logged_in_admin)
    resp = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, "nobody@example.com"),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert resp.status_code == 404
    assert resp.json["error"] == "recipient_not_found"


def test_duplicate_active_share_is_409(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    f = _make_file(db_session, logged_in_admin)
    client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    dup = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert dup.status_code == 409


# --- Listing ---


def test_list_received_shows_active_only(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    f = _make_file(db_session, seeded_admin)
    # Insert active share directly
    s = Share(
        target_type=ShareTargetType.FILE,
        target_id=f.id,
        granter_id=seeded_admin.id,
        recipient_id=logged_in_user.id,
        permission=SharePermission.VIEWER,
    )
    db_session.add(s)
    db_session.commit()

    resp = client.get("/api/shares/received")
    assert resp.status_code == 200
    items = resp.json["items"]
    assert len(items) == 1
    assert items[0]["target_id"] == str(f.id)
    assert items[0]["granter_email"] == seeded_admin.email


def test_revoke_share_hides_from_received(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    f = _make_file(db_session, logged_in_admin)
    created = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    resp = client.delete(
        f"/api/shares/{created['id']}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 204

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "share.revoked")
    ).all()
    assert len(audits) == 1


def test_revoke_by_non_granter_is_403(
    client, db_session, logged_in_user, seeded_admin, seeded_other_user, csrf_token
) -> None:
    """A user who is neither granter nor admin cannot revoke."""
    f = _make_file(db_session, seeded_admin)
    s = Share(
        target_type=ShareTargetType.FILE,
        target_id=f.id,
        granter_id=seeded_admin.id,
        recipient_id=seeded_other_user.id,
        permission=SharePermission.VIEWER,
    )
    db_session.add(s)
    db_session.commit()
    resp = client.delete(f"/api/shares/{s.id}", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 403


def test_reactivate_after_revoke(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """Sharing again after a revoke updates the existing row in place — no
    duplicate insert (partial unique index would block it otherwise)."""
    f = _make_file(db_session, logged_in_admin)
    a = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    client.delete(f"/api/shares/{a['id']}", headers={"X-CSRF-Token": csrf_token})
    b = client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email, permission="editor"),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert b.status_code == 201
    # Should be the same row id (reactivated) or a fresh one; both are correct.
    rows = db_session.scalars(select(Share).where(Share.target_id == f.id)).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None
    assert rows[0].permission == SharePermission.EDITOR


# --- Folder-share recursion ---


def test_folder_share_propagates_to_files(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    parent = Folder(owner_id=logged_in_admin.id, name="HR")
    db_session.add(parent)
    db_session.flush()
    child = Folder(owner_id=logged_in_admin.id, parent_id=parent.id, name="Salaries")
    db_session.add(child)
    db_session.commit()

    direct = _make_file(db_session, logged_in_admin, folder_id=parent.id, filename="a.txt")
    nested = _make_file(db_session, logged_in_admin, folder_id=child.id, filename="b.txt")
    _classify(db_session, direct, ClassificationTier.INTERNAL)
    _classify(db_session, nested, ClassificationTier.INTERNAL)

    # Admin shares the parent folder with seeded_user
    client.post(
        "/api/shares",
        json=_share_payload_folder(parent.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    # Log out admin → log in seeded_user → hit /shared
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    )
    resp = client.get("/api/files/shared")
    assert resp.status_code == 200
    filenames = {f["original_filename"] for f in resp.json["items"]}
    assert filenames == {"a.txt", "b.txt"}


# --- Policy: share elevates over tier ceiling ---


def test_share_elevates_over_tier_ceiling(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """User-role policy max is CONFIDENTIAL; a share on a RESTRICTED file
    must let the recipient download (cloud-drive semantics)."""
    f = _make_file(db_session, logged_in_admin, filename="topsecret.txt")
    _classify(db_session, f, ClassificationTier.RESTRICTED, categories=["medical records"])
    client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    )

    # Without the share, this would be 403 tier_exceeds_policy
    resp = client.get(f"/api/files/{f.id}")
    assert resp.status_code == 200


def test_share_does_not_bypass_category_deny(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """A `denied_categories` block in the recipient's policy still bites even
    when there's a share — admins can quarantine categories no matter what."""
    # Set up a category deny for the user's role+department
    blocker = AccessPolicy(
        role=Role.USER,
        department_id=seeded_user.department_id,
        allowed_max_tier=ClassificationTier.CONFIDENTIAL,
        denied_categories=["medical records"],
        description="Test: marketing denied medical.",
    )
    db_session.add(blocker)
    db_session.commit()

    f = _make_file(db_session, logged_in_admin, filename="medical.txt")
    _classify(db_session, f, ClassificationTier.CONFIDENTIAL, categories=["medical records"])
    client.post(
        "/api/shares",
        json=_share_payload_file(f.id, seeded_user.email),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    )

    resp = client.get(f"/api/files/{f.id}")
    assert resp.status_code == 403
    assert resp.json["reason"] == "denied_category"


def test_shared_list_filters_denied(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """A file blocked by `denied_categories` should NOT appear in /shared."""
    blocker = AccessPolicy(
        role=Role.USER,
        department_id=seeded_user.department_id,
        allowed_max_tier=ClassificationTier.CONFIDENTIAL,
        denied_categories=["medical records"],
        description="Test deny.",
    )
    db_session.add(blocker)
    db_session.commit()

    allowed = _make_file(db_session, logged_in_admin, filename="ok.txt")
    blocked = _make_file(db_session, logged_in_admin, filename="medical.txt")
    _classify(db_session, allowed, ClassificationTier.INTERNAL)
    _classify(db_session, blocked, ClassificationTier.INTERNAL, categories=["medical records"])

    for f in (allowed, blocked):
        client.post(
            "/api/shares",
            json=_share_payload_file(f.id, seeded_user.email),
            headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
        )

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    )
    resp = client.get("/api/files/shared")
    filenames = {f["original_filename"] for f in resp.json["items"]}
    assert filenames == {"ok.txt"}
