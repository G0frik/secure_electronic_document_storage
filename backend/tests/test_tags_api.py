"""Phase 10 — /api/files/<id>/tags API tests."""

from __future__ import annotations

import io
import uuid

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.tag import FileTag, Tag


def _upload(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def _add(client, csrf_token, file_id, names):
    return client.post(
        f"/api/files/{file_id}/tags",
        json={"names": names},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )


# --- Add / list ---


def test_add_tags_creates_them(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]

    resp = _add(client, csrf_token, file_id, ["Q3", "draft"])
    assert resp.status_code == 201
    names = {t["name"] for t in resp.json["items"]}
    assert names == {"q3", "draft"}  # normalised to lowercase

    # Tag rows exist in `tags`
    tags = db_session.scalars(select(Tag)).all()
    assert {t.name for t in tags} == {"q3", "draft"}

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "tag.added")
    ).all()
    assert len(audits) == 2


def test_adding_same_tag_twice_is_idempotent(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]
    _add(client, csrf_token, file_id, ["q3"])
    again = _add(client, csrf_token, file_id, ["q3", "Q3", "  Q3  "])
    assert again.status_code == 201
    items = again.json["items"]
    assert [t["name"] for t in items] == ["q3"]

    # Only one FileTag row total
    rows = db_session.scalars(select(FileTag)).all()
    assert len(rows) == 1


def test_list_tags_returns_sorted_by_name(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]
    _add(client, csrf_token, file_id, ["zebra", "alpha", "kilo"])

    resp = client.get(f"/api/files/{file_id}/tags")
    assert resp.status_code == 200
    assert [t["name"] for t in resp.json["items"]] == ["alpha", "kilo", "zebra"]


def test_empty_or_whitespace_tag_is_400(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]
    resp = _add(client, csrf_token, file_id, ["   "])
    assert resp.status_code == 400
    assert resp.json["error"] == "invalid_tag"


def test_per_file_cap_enforced(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]
    # Add 32 (cap) — should succeed
    big = [f"tag-{i:02d}" for i in range(32)]
    ok = _add(client, csrf_token, file_id, big)
    assert ok.status_code == 201
    # The 33rd push fails
    bad = _add(client, csrf_token, file_id, ["one-too-many"])
    assert bad.status_code == 409
    assert bad.json["error"] == "too_many_tags"


# --- Cross-owner ---


def test_other_user_cannot_add_tags(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    """Tags are an owner-only operation; non-owners can't add even if they
    have policy access to read the file."""
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

    resp = _add(client, csrf_token, f.id, ["mine"])
    assert resp.status_code == 404


# --- Remove ---


def test_remove_tag(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]
    added = _add(client, csrf_token, file_id, ["temp"]).json
    tag_id = added["items"][0]["id"]

    resp = client.delete(
        f"/api/files/{file_id}/tags/{tag_id}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 204

    # Tag still exists globally (could be re-attached or shared with other files)
    # but the FileTag row is gone.
    rows = db_session.scalars(select(FileTag)).all()
    assert rows == []
    assert db_session.scalar(select(Tag).where(Tag.id == uuid.UUID(tag_id))) is not None

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "tag.removed")
    ).all()
    assert len(audits) == 1


def test_remove_unknown_tag_is_204(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """Remove of a tag-that-was-never-applied is a no-op (idempotent)."""
    up = _upload(client, csrf_token, "x.txt", b"hi")
    file_id = up.json["id"]
    resp = client.delete(
        f"/api/files/{file_id}/tags/{uuid.uuid4()}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 204
