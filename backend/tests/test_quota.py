"""Phase 12 — per-user storage quota tests."""

from __future__ import annotations

import io
import uuid
from datetime import UTC

from sqlalchemy import select

from app.models.file import File
from app.services import quota


def _upload(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


# --- Defaults + bookkeeping ---


def test_new_user_has_2gb_quota(client, db_session, logged_in_admin) -> None:
    assert logged_in_admin.quota_bytes == 2 * 1024 * 1024 * 1024
    assert logged_in_admin.used_bytes == 0


def test_upload_increments_used_bytes(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"x" * 500
    resp = _upload(client, csrf_token, "x.txt", body)
    assert resp.status_code == 201

    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 500

    # Second upload accumulates
    _upload(client, csrf_token, "y.txt", b"y" * 250)
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 750


def test_auth_me_includes_quota(client, db_session, logged_in_admin, csrf_token) -> None:
    _upload(client, csrf_token, "x.txt", b"x" * 1000)
    me = client.get("/api/auth/me").json
    assert me["quota_bytes"] == 2 * 1024 * 1024 * 1024
    assert me["used_bytes"] == 1000


# --- Quota enforcement ---


def test_upload_at_exact_quota_succeeds(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """An upload that exactly fills the bucket is allowed; one byte more isn't."""
    logged_in_admin.quota_bytes = 1024
    db_session.commit()

    ok = _upload(client, csrf_token, "fits.bin", b"\x00" * 1024)
    assert ok.status_code == 201

    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 1024

    over = _upload(client, csrf_token, "spills.bin", b"\x00")
    assert over.status_code == 413
    body = over.json
    assert body["error"] == "quota_exceeded"
    assert body["used_bytes"] == 1024
    assert body["quota_bytes"] == 1024
    assert body["requested_bytes"] == 1
    assert body["available_bytes"] == 0


def test_upload_over_quota_does_not_persist_file(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """When 413 fires, no File row is created and no MinIO object is written."""
    logged_in_admin.quota_bytes = 100
    db_session.commit()

    files_before = db_session.scalars(select(File)).all()
    resp = _upload(client, csrf_token, "huge.bin", b"\x00" * 200)
    assert resp.status_code == 413

    files_after = db_session.scalars(select(File)).all()
    assert len(files_after) == len(files_before)
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 0


def test_separate_users_have_separate_quotas(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """Tightening one user's quota doesn't shrink someone else's."""
    seeded_user.quota_bytes = 50
    db_session.commit()

    # The admin can still upload comfortably under their default 2 GiB.
    _upload(client, csrf_token, "fine.txt", b"x" * 10_000)
    db_session.refresh(logged_in_admin)
    db_session.refresh(seeded_user)
    assert logged_in_admin.used_bytes == 10_000
    assert seeded_user.used_bytes == 0


# --- Trash + hard-delete ---


def test_soft_delete_does_not_free_quota(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """Trash retains the file; quota counter stays."""
    up = _upload(client, csrf_token, "x.txt", b"x" * 500).json
    client.delete(f"/api/files/{up['id']}", headers={"X-CSRF-Token": csrf_token})

    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 500


def test_restore_does_not_double_count(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"x" * 500).json
    client.delete(f"/api/files/{up['id']}", headers={"X-CSRF-Token": csrf_token})
    client.post(
        f"/api/trash/{up['id']}/restore", headers={"X-CSRF-Token": csrf_token}
    )
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 500


def test_hard_delete_frees_quota(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"x" * 500).json
    client.delete(f"/api/files/{up['id']}", headers={"X-CSRF-Token": csrf_token})
    client.delete(f"/api/trash/{up['id']}", headers={"X-CSRF-Token": csrf_token})

    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 0


def test_reaper_frees_quota(client, db_session, logged_in_admin, csrf_token) -> None:
    """Reaper-driven hard-delete decrements the counter the same way."""
    from datetime import datetime, timedelta

    from app.services import trash

    up = _upload(client, csrf_token, "x.txt", b"x" * 500).json
    client.delete(f"/api/files/{up['id']}", headers={"X-CSRF-Token": csrf_token})

    # Back-date the trashed file past the cutoff.
    row = db_session.scalar(select(File).where(File.id == uuid.UUID(up["id"])))
    row.deleted_at = datetime.now(UTC) - timedelta(days=31)
    db_session.commit()

    purged = trash.reap_expired_trash(retention_days=30)
    assert purged == 1
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 0


# --- Drift recompute ---


def test_recompute_fixes_drift(client, db_session, logged_in_admin, csrf_token) -> None:
    """Manually corrupt `used_bytes`; recompute should restore truth."""
    _upload(client, csrf_token, "a.txt", b"a" * 100)
    _upload(client, csrf_token, "b.txt", b"b" * 200)
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 300

    # Simulate drift
    logged_in_admin.used_bytes = 999_999
    db_session.commit()

    affected = quota.recompute_all()
    assert affected >= 1
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 300


def test_recompute_for_user_zeroes_no_files(
    client, db_session, seeded_user
) -> None:
    """Drift on a user with no files snaps back to 0."""
    seeded_user.used_bytes = 12_345
    db_session.commit()
    quota.recompute_for(seeded_user)
    db_session.commit()
    db_session.refresh(seeded_user)
    assert seeded_user.used_bytes == 0


# --- Edge cases ---


def test_decrement_clamps_at_zero(client, db_session, seeded_user) -> None:
    """Negative counters never happen — clamp on decrement."""
    seeded_user.used_bytes = 100
    quota.decrement_used(seeded_user, 500)
    assert seeded_user.used_bytes == 0


def test_zero_byte_upload_rejected_before_quota(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """Empty upload error wins over quota; counter not touched."""
    resp = _upload(client, csrf_token, "empty.txt", b"")
    assert resp.status_code == 400
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.used_bytes == 0


def test_quota_check_with_no_owner_quota_at_zero(
    db_session, seeded_user
) -> None:
    """A user with quota_bytes=0 (admin lockout) can't upload anything."""
    seeded_user.quota_bytes = 0
    db_session.commit()
    try:
        quota.check_quota_for_upload(seeded_user, 1)
        raise AssertionError("expected QuotaExceededError")
    except quota.QuotaExceededError as exc:
        assert exc.requested == 1
        assert exc.quota == 0
        assert exc.available == 0
