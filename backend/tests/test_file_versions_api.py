"""Phase 15 — file versioning tests.

Covers:
  * Upload-new-version snapshots prior content, bumps `current_version`
  * Quota accumulates per version
  * Listing returns current + history, newest-first
  * Download current via /versions/<v>/download === regular download
  * Download a HISTORICAL version returns the snapshotted bytes
  * Historical version 404 when version_number doesn't exist
  * Non-owner can't list/upload/download historical (owner-only)
  * Hard delete removes all version MinIO blobs + frees quota
  * Reaper removes historical versions older than the cutoff, never current
  * Delete-version endpoint refuses current, deletes history
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.services import file_versions, storage


def _upload_initial(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _upload_version(client, csrf_token, file_id, filename, content, content_type="text/plain"):
    return client.post(
        f"/api/files/{file_id}/versions",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def test_upload_new_version_bumps_current_and_snapshots_prior(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    v1_body = b"version one bytes"
    up = _upload_initial(client, csrf_token, "doc.txt", v1_body)
    file_id = up.json["id"]
    assert up.json["current_version"] == 1

    v2_body = b"version two has different bytes entirely"
    up2 = _upload_version(client, csrf_token, file_id, "doc.txt", v2_body)
    assert up2.status_code == 201, up2.data
    assert up2.json["current_version"] == 2
    assert up2.json["size_bytes"] == len(v2_body)

    # DB invariants
    file_row = db_session.scalar(select(File).where(File.id == uuid.UUID(file_id)))
    assert file_row.current_version == 2
    history = db_session.scalars(
        select(FileVersion).where(FileVersion.file_id == file_row.id)
    ).all()
    assert len(history) == 1
    assert history[0].version_number == 1
    assert history[0].size_bytes == len(v1_body)


def test_upload_new_version_emits_version_uploaded_audit(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "x.txt", b"a")
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "x.txt", b"bb")

    rows = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.version_uploaded")
    ).all()
    assert len(rows) == 1
    assert rows[0].event_metadata["new_version"] == 2
    assert rows[0].event_metadata["snapshot_version"] == 1


def test_quota_accumulates_per_version(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    v1 = b"x" * 100
    up = _upload_initial(client, csrf_token, "q.txt", v1)
    file_id = up.json["id"]
    me1 = client.get("/api/auth/me").json
    assert me1["used_bytes"] == 100

    v2 = b"y" * 250
    _upload_version(client, csrf_token, file_id, "q.txt", v2)
    me2 = client.get("/api/auth/me").json
    # Old version still in MinIO + quota; new version added on top.
    assert me2["used_bytes"] == 350


def test_list_versions_returns_current_plus_history_newest_first(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "v.txt", b"v1")
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "v.txt", b"v22")
    _upload_version(client, csrf_token, file_id, "v.txt", b"v333")

    response = client.get(f"/api/files/{file_id}/versions")
    assert response.status_code == 200
    items = response.json["items"]
    assert [v["version_number"] for v in items] == [3, 2, 1]
    assert items[0]["is_current"] is True
    assert all(v["is_current"] is False for v in items[1:])


def test_download_current_via_versions_endpoint(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "d.txt", b"current bytes")
    file_id = up.json["id"]
    response = client.get(f"/api/files/{file_id}/versions/1/download")
    assert response.status_code == 200
    assert response.data == b"current bytes"


def test_download_historical_version_returns_snapshot_bytes(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "h.txt", b"first content")
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "h.txt", b"replaced content")

    # Historical (v1) → snapshot bytes
    r1 = client.get(f"/api/files/{file_id}/versions/1/download")
    assert r1.status_code == 200
    assert r1.data == b"first content"

    # Current (v2) → new bytes
    r2 = client.get(f"/api/files/{file_id}/versions/2/download")
    assert r2.status_code == 200
    assert r2.data == b"replaced content"


def test_download_unknown_version_404(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "u.txt", b"only-v1")
    file_id = up.json["id"]
    response = client.get(f"/api/files/{file_id}/versions/99/download")
    assert response.status_code == 404


def test_non_owner_cannot_upload_version(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    """Phase 15: versions are owner-only — Alice cannot push a new version
    of admin's file even though Alice's role policy might allow reading it.
    """
    # Admin's pre-existing file inserted directly (we can't log in as 2 users at once)
    f = File(
        owner_id=seeded_admin.id,
        original_filename="theirs.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=4,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(f)
    db_session.commit()
    response = client.post(
        f"/api/files/{f.id}/versions",
        data={"file": (io.BytesIO(b"hi"), "x.txt", "text/plain")},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    assert response.status_code == 404  # anti-enumeration: same as missing


def test_non_owner_non_admin_cannot_list_versions(
    client, db_session, logged_in_user, seeded_admin
) -> None:
    f = File(
        owner_id=seeded_admin.id,
        original_filename="theirs.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=4,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(f)
    db_session.commit()
    response = client.get(f"/api/files/{f.id}/versions")
    assert response.status_code == 403


def test_non_owner_cannot_download_historical_version(
    client, db_session, logged_in_user, seeded_admin
) -> None:
    """Sharing semantics don't extend to old versions. Even if the user
    could read the current version (via a share + classification), the
    historical version is owner/admin-only.
    """
    # Build a file + a historical version directly so we don't need to log
    # in as two different users.
    f = File(
        owner_id=seeded_admin.id,
        original_filename="cur.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=4,
        sha256="a" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
        current_version=2,
    )
    db_session.add(f)
    db_session.flush()
    v = FileVersion(
        file_id=f.id,
        version_number=1,
        storage_key=uuid.uuid4(),
        original_filename="old.txt",
        mime_type="text/plain",
        size_bytes=4,
        sha256="b" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
        uploader_id=seeded_admin.id,
    )
    db_session.add(v)
    db_session.commit()

    response = client.get(f"/api/files/{f.id}/versions/1/download")
    assert response.status_code == 403


def test_delete_version_refuses_current(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "del.txt", b"only-v1")
    file_id = up.json["id"]
    response = client.delete(
        f"/api/files/{file_id}/versions/1",
        headers={"X-CSRF-Token": csrf_token},
    )
    # v1 is current here
    assert response.status_code == 409
    assert response.json["error"] == "invalid_request"


def test_delete_historical_version_frees_quota_and_removes_blob(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "del.txt", b"x" * 100)
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "del.txt", b"y" * 250)

    # Capture the historical version's storage_key for the MinIO check.
    historical = db_session.scalar(
        select(FileVersion).where(
            FileVersion.file_id == uuid.UUID(file_id),
            FileVersion.version_number == 1,
        )
    )
    historical_key = str(historical.storage_key)
    assert historical_key in set(storage.list_keys())

    response = client.delete(
        f"/api/files/{file_id}/versions/1",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 204

    # Quota freed by the 100 B of v1
    me = client.get("/api/auth/me").json
    assert me["used_bytes"] == 250

    # MinIO blob gone
    assert historical_key not in set(storage.list_keys())

    # Row gone
    still_there = db_session.scalar(
        select(FileVersion).where(
            FileVersion.file_id == uuid.UUID(file_id),
            FileVersion.version_number == 1,
        )
    )
    assert still_there is None


def test_hard_delete_file_removes_all_version_blobs_and_frees_quota(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "h.txt", b"x" * 100)
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "h.txt", b"y" * 250)

    # Grab both storage_keys before deletion
    file_row = db_session.scalar(
        select(File).where(File.id == uuid.UUID(file_id))
    )
    current_key = str(file_row.storage_key)
    historical = db_session.scalar(
        select(FileVersion).where(FileVersion.file_id == file_row.id)
    )
    historical_key = str(historical.storage_key)

    # Soft delete → hard delete
    client.delete(f"/api/files/{file_id}", headers={"X-CSRF-Token": csrf_token})
    client.delete(f"/api/trash/{file_id}", headers={"X-CSRF-Token": csrf_token})

    keys = set(storage.list_keys())
    assert current_key not in keys
    assert historical_key not in keys

    me = client.get("/api/auth/me").json
    assert me["used_bytes"] == 0


def test_reaper_removes_old_historical_versions_but_keeps_current(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "r.txt", b"x" * 100)
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "r.txt", b"y" * 250)
    _upload_version(client, csrf_token, file_id, "r.txt", b"z" * 75)

    # Backdate the v1 + v2 snapshots so the 30-day reaper hits them
    long_ago = datetime.now(UTC) - timedelta(days=90)
    db_session.execute(
        FileVersion.__table__.update()
        .where(FileVersion.file_id == uuid.UUID(file_id))
        .values(uploaded_at=long_ago)
    )
    db_session.commit()

    removed = file_versions.reap_expired_versions(retention_days=30)
    assert removed == 2

    # Current still there
    file_row = db_session.scalar(
        select(File).where(File.id == uuid.UUID(file_id))
    )
    assert file_row is not None
    assert file_row.current_version == 3

    # No history left
    leftover = db_session.scalars(
        select(FileVersion).where(FileVersion.file_id == uuid.UUID(file_id))
    ).all()
    assert leftover == []

    # Quota freed by (100 + 250); current 75 stays
    me = client.get("/api/auth/me").json
    assert me["used_bytes"] == 75


def test_reaper_skips_recent_versions(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload_initial(client, csrf_token, "rs.txt", b"a")
    file_id = up.json["id"]
    _upload_version(client, csrf_token, file_id, "rs.txt", b"bb")

    # Default uploaded_at = NOW, well within retention.
    removed = file_versions.reap_expired_versions(retention_days=30)
    assert removed == 0
    leftover = db_session.scalars(
        select(FileVersion).where(FileVersion.file_id == uuid.UUID(file_id))
    ).all()
    assert len(leftover) == 1


def test_upload_new_version_enforces_quota(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """Set quota to 100 B, upload 60 B v1, then try a 60 B v2 (60+60>100)."""
    admin = db_session.scalar(select(User).where(User.email == "admin@docstore.app"))
    admin.quota_bytes = 100
    db_session.commit()

    up = _upload_initial(client, csrf_token, "q.txt", b"x" * 60)
    file_id = up.json["id"]
    response = _upload_version(client, csrf_token, file_id, "q.txt", b"y" * 60)
    assert response.status_code == 413
    assert response.json["error"] == "quota_exceeded"

    # No new version row, no new MinIO blob — fail-fast happens before encryption.
    history = db_session.scalars(
        select(FileVersion).where(FileVersion.file_id == uuid.UUID(file_id))
    ).all()
    assert history == []
