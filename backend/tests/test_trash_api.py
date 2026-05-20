"""Phase 9 — trash (soft delete) tests.

Covers:
  - DELETE /api/files/<id> soft-deletes; the file disappears from /api/files
  - /api/trash lists trashed files
  - Restore brings it back into /api/files; folder_id preserved
  - Restore moves orphans (parent folder gone) to root
  - Hard-delete from /api/trash removes the MinIO ciphertext + DB row
  - Public share-link returns 410 file_removed for trashed files (restore re-enables it)
  - Internal shares hide trashed files from "Shared with me"
  - Reaper hard-deletes only rows past the retention cutoff
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.file import File
from app.models.folder import Folder
from app.models.share import Share, SharePermission, ShareTargetType
from app.models.share_link import ShareLink
from app.services import storage, trash


def _upload(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _classify(db_session, file_id, tier=ClassificationTier.PUBLIC, categories=None):
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
    existing.classified_at = datetime.now(timezone.utc)
    db_session.commit()
    return existing


# --- Soft delete + list + restore ---


def test_delete_file_soft_deletes(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hello")
    file_id = up.json["id"]

    resp = client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    assert resp.status_code == 204

    # Row still exists in DB but with deleted_at set
    row = db_session.scalar(select(File).where(File.id == uuid.UUID(file_id)))
    assert row is not None
    assert row.deleted_at is not None

    # Vanishes from normal listing
    listing = client.get("/api/files").json
    assert listing["total"] == 0
    assert listing["items"] == []

    # Audit row exists
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.soft_deleted")
    ).all()
    assert len(audits) == 1


def test_trash_list_shows_only_trashed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    live = _upload(client, csrf_token, "live.txt", b"live").json
    trashed = _upload(client, csrf_token, "trashed.txt", b"trashed").json
    client.delete(f"/api/files/{trashed['id']}", headers={"X-CSRF-Token": csrf_token})

    resp = client.get("/api/trash")
    items = resp.json["items"]
    assert {f["original_filename"] for f in items} == {"trashed.txt"}
    assert items[0]["deleted_at"] is not None
    # Live file not present
    assert live["id"] not in {f["id"] for f in items}


def test_get_metadata_404_when_trashed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hello")
    file_id = up.json["id"]
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})

    resp = client.get(f"/api/files/{file_id}")
    assert resp.status_code == 404


def test_download_404_when_trashed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hello")
    file_id = up.json["id"]
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})

    resp = client.get(f"/api/files/{file_id}/download")
    assert resp.status_code == 404


def test_restore_brings_back_into_listing(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hello")
    file_id = up.json["id"]
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})

    resp = client.post(
        f"/api/trash/{file_id}/restore", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 200
    assert resp.json["deleted_at"] is None

    # Back in normal listing
    listing = client.get("/api/files").json
    assert listing["total"] == 1
    # Gone from trash
    assert client.get("/api/trash").json["items"] == []

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.restored")
    ).all()
    assert len(audits) == 1


def test_restore_preserves_folder(client, db_session, logged_in_admin, csrf_token) -> None:
    folder = client.post(
        "/api/folders",
        json={"name": "Stuff"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    up = client.post(
        "/api/files",
        data={
            "file": (io.BytesIO(b"hi"), "x.txt", "text/plain"),
            "folder_id": folder["id"],
        },
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    ).json
    client.delete(f"/api/files/{up['id']}", headers={"X-CSRF-Token": csrf_token})
    restored = client.post(
        f"/api/trash/{up['id']}/restore", headers={"X-CSRF-Token": csrf_token}
    ).json
    assert restored["folder_id"] == folder["id"]


def test_restore_orphan_moves_to_root(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """If the parent folder has been removed while the file was in trash, the
    restored file lands at root.
    """
    folder = client.post(
        "/api/folders",
        json={"name": "WillVanish"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    up = client.post(
        "/api/files",
        data={
            "file": (io.BytesIO(b"hi"), "x.txt", "text/plain"),
            "folder_id": folder["id"],
        },
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    ).json
    client.delete(f"/api/files/{up['id']}", headers={"X-CSRF-Token": csrf_token})
    # Folder is now empty (we soft-deleted the file) — delete the folder
    client.delete(f"/api/folders/{folder['id']}", headers={"X-CSRF-Token": csrf_token})

    restored = client.post(
        f"/api/trash/{up['id']}/restore", headers={"X-CSRF-Token": csrf_token}
    ).json
    assert restored["folder_id"] is None


# --- Hard delete + MinIO cleanup ---


def test_hard_delete_removes_minio_and_row(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"will be hard-deleted"
    up = _upload(client, csrf_token, "doomed.txt", body).json
    file_id = up.json["id"] if "json" in dir(up) else up["id"]
    row = db_session.scalar(select(File).where(File.id == uuid.UUID(file_id)))
    storage_key = str(row.storage_key)
    assert storage.list_keys is not None  # smoke

    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})

    resp = client.delete(
        f"/api/trash/{file_id}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 204

    # Row gone
    assert db_session.scalar(select(File).where(File.id == uuid.UUID(file_id))) is None
    # MinIO object gone
    assert storage_key not in list(storage.list_keys())

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.hard_deleted")
    ).all()
    assert len(audits) == 1
    assert audits[0].severity.value == "warning"


def test_hard_delete_requires_trash_first(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """Calling /api/trash/<id> DELETE on a live file is rejected — caller
    must soft-delete first so they see the file in trash before purging."""
    up = _upload(client, csrf_token, "x.txt", b"hi")
    resp = client.delete(
        f"/api/trash/{up.json['id']}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 409


# --- Share-link + share interactions ---


def test_share_link_returns_410_when_trashed(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"link target"
    up = _upload(client, csrf_token, "x.txt", body)
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.PUBLIC)

    minted = client.post(
        "/api/share-links",
        json={"file_id": str(file_id)},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    # Trash the file → the live link should now 410 with reason=file_removed
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    resp = client.get(f"/api/public/share-links/{minted['token']}")
    assert resp.status_code == 410
    assert resp.json["reason"] == "file_removed"


def test_share_link_works_again_after_restore(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"link bytes"
    up = _upload(client, csrf_token, "x.txt", body)
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.PUBLIC)

    minted = client.post(
        "/api/share-links",
        json={"file_id": str(file_id)},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    client.post(f"/api/trash/{file_id}/restore", headers={"X-CSRF-Token": csrf_token})

    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    resp = client.get(f"/api/public/share-links/{minted['token']}")
    assert resp.status_code == 200
    download = client.get(f"/api/public/share-links/{minted['token']}/download")
    assert download.data == body


def test_internal_share_hides_trashed_file(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """A file shared with another user disappears from their /api/files/shared
    once the owner trashes it."""
    body = b"shared"
    up = _upload(client, csrf_token, "x.txt", body)
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.PUBLIC)

    client.post(
        "/api/shares",
        json={
            "target_type": "file",
            "target_id": str(file_id),
            "recipient_email": seeded_user.email,
            "permission": "viewer",
        },
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})

    # Switch to the recipient and look at /api/files/shared
    client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    new_csrf = client.get("/api/auth/csrf").json["csrf_token"]
    client.post(
        "/api/auth/login",
        json={"email": seeded_user.email, "password": "AlicePassword123!"},
        headers={"X-CSRF-Token": new_csrf, "Content-Type": "application/json"},
    )
    resp = client.get("/api/files/shared")
    assert resp.status_code == 200
    assert resp.json["items"] == []


# --- Hard-delete cascade through shares + share_links ---


def test_hard_delete_cleans_shares_and_links(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = uuid.UUID(up.json["id"])
    _classify(db_session, file_id, ClassificationTier.PUBLIC)

    # Internal share
    client.post(
        "/api/shares",
        json={
            "target_type": "file",
            "target_id": str(file_id),
            "recipient_email": seeded_user.email,
        },
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    # External link
    client.post(
        "/api/share-links",
        json={"file_id": str(file_id)},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )

    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    client.delete(f"/api/trash/{file_id}", headers={"X-CSRF-Token": csrf_token})

    # Share row gone (polymorphic delete in service)
    assert (
        db_session.scalar(
            select(Share).where(
                Share.target_type == ShareTargetType.FILE,
                Share.target_id == file_id,
            )
        )
        is None
    )
    # Share link gone via FK CASCADE
    assert (
        db_session.scalar(select(ShareLink).where(ShareLink.file_id == file_id))
        is None
    )


# --- Reaper ---


def test_reaper_purges_only_expired(client, db_session, logged_in_admin, csrf_token) -> None:
    """30-day retention by default. Back-date one file beyond the cutoff and
    leave the other fresh — only the old one should be hard-deleted.
    """
    old = _upload(client, csrf_token, "old.txt", b"old").json
    fresh = _upload(client, csrf_token, "fresh.txt", b"fresh").json
    client.delete(f"/api/files/{old['id']}", headers={"X-CSRF-Token": csrf_token})
    client.delete(f"/api/files/{fresh['id']}", headers={"X-CSRF-Token": csrf_token})

    # Back-date the "old" trashed file to 31 days ago
    old_row = db_session.scalar(select(File).where(File.id == uuid.UUID(old["id"])))
    old_row.deleted_at = datetime.now(timezone.utc) - timedelta(days=31)
    db_session.commit()

    count = trash.reap_expired_trash(retention_days=30)
    assert count == 1

    assert (
        db_session.scalar(select(File).where(File.id == uuid.UUID(old["id"]))) is None
    )
    assert (
        db_session.scalar(select(File).where(File.id == uuid.UUID(fresh["id"]))) is not None
    )

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "trash.reaped")
    ).all()
    assert len(audits) == 1
    assert audits[-1].event_metadata["count"] == 1


def test_reaper_noop_when_empty(client, db_session, logged_in_admin) -> None:
    count = trash.reap_expired_trash(retention_days=30)
    assert count == 0
