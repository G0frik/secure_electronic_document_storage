"""Tests for /api/files/* endpoints."""

from __future__ import annotations

import hashlib
import io
import uuid

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.file import File
from app.services import storage


def _upload(client, csrf_token, filename, content, content_type="text/plain"):
    return client.post(
        "/api/files",
        data={"file": (io.BytesIO(content), filename, content_type)},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )


def test_upload_requires_auth(client, csrf_token) -> None:
    response = _upload(client, csrf_token, "x.txt", b"hello")
    assert response.status_code == 401


def test_upload_requires_csrf(client, db_session, logged_in_admin) -> None:
    response = client.post(
        "/api/files",
        data={"file": (io.BytesIO(b"hi"), "x.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 403


def test_upload_returns_metadata_and_audits(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"the quick brown fox\n"
    response = _upload(client, csrf_token, "fox.txt", body, "text/plain")
    assert response.status_code == 201, response.data
    payload = response.json
    assert payload["original_filename"] == "fox.txt"
    assert payload["size_bytes"] == len(body)
    assert payload["mime_type"] == "text/plain"
    assert payload["sha256"] == hashlib.sha256(body).hexdigest()
    assert payload["owner_id"] == str(logged_in_admin.id)
    # Row in DB
    rows = db_session.scalars(select(File)).all()
    assert len(rows) == 1
    # Audit row
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.uploaded")
    ).all()
    assert len(audits) == 1


def test_upload_rejects_missing_file_field(client, db_session, logged_in_admin, csrf_token) -> None:
    response = client.post(
        "/api/files",
        data={},
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_upload_rejects_empty_file(client, db_session, logged_in_admin, csrf_token) -> None:
    response = _upload(client, csrf_token, "empty.txt", b"")
    assert response.status_code == 400
    assert response.json["error"] == "empty_upload"


def test_list_empty(client, db_session, logged_in_admin) -> None:
    response = client.get("/api/files")
    assert response.status_code == 200
    assert response.json == {"items": [], "page": 1, "per_page": 50, "total": 0}


def test_list_returns_files_and_audits(client, db_session, logged_in_admin, csrf_token) -> None:
    for i in range(3):
        _upload(client, csrf_token, f"f{i}.txt", f"content-{i}".encode())
    response = client.get("/api/files")
    assert response.status_code == 200
    assert response.json["total"] == 3
    assert len(response.json["items"]) == 3
    # Audit for the list call
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.listed")
    ).all()
    assert len(audits) >= 1


def test_list_pagination(client, db_session, logged_in_admin, csrf_token) -> None:
    for i in range(5):
        _upload(client, csrf_token, f"p{i}.txt", f"p-{i}".encode())
    page1 = client.get("/api/files?page=1&per_page=2").json
    page2 = client.get("/api/files?page=2&per_page=2").json
    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert page1["items"][0]["id"] != page2["items"][0]["id"]


def test_list_only_shows_own_files(
    client, db_session, logged_in_admin, csrf_token, seeded_other_user
) -> None:
    # Upload one file as the logged-in admin
    _upload(client, csrf_token, "mine.txt", b"mine")
    # Insert a file directly for the other user
    other_file = File(
        owner_id=seeded_other_user.id,
        original_filename="theirs.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=10,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(other_file)
    db_session.commit()

    response = client.get("/api/files")
    assert response.json["total"] == 1
    assert response.json["items"][0]["original_filename"] == "mine.txt"


def test_get_metadata(client, db_session, logged_in_admin, csrf_token) -> None:
    up = _upload(client, csrf_token, "meta.txt", b"data")
    file_id = up.json["id"]
    response = client.get(f"/api/files/{file_id}")
    assert response.status_code == 200
    assert response.json["id"] == file_id


def test_get_metadata_not_found(client, db_session, logged_in_admin) -> None:
    response = client.get(f"/api/files/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_metadata_for_other_users_file_returns_404(
    client, db_session, logged_in_admin, seeded_other_user
) -> None:
    other_file = File(
        owner_id=seeded_other_user.id,
        original_filename="secret.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=10,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(other_file)
    db_session.commit()
    response = client.get(f"/api/files/{other_file.id}")
    assert response.status_code == 404


def test_download_returns_original_bytes_and_audits(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    body = b"\x00\x01\x02hello-binary\xff\xfe"
    up = _upload(client, csrf_token, "blob.bin", body, "application/octet-stream")
    file_id = up.json["id"]
    response = client.get(f"/api/files/{file_id}/download")
    assert response.status_code == 200
    assert response.data == body
    assert response.headers["Content-Type"].startswith("application/octet-stream")
    assert 'filename="blob.bin"' in response.headers["Content-Disposition"]
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "file.downloaded")
    ).all()
    assert len(audits) == 1


def test_minio_stores_ciphertext_not_plaintext(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    """The bytes in MinIO must NOT match the plaintext upload — they're AES-GCM ciphertext."""
    plaintext = b"plaintext-marker-must-not-appear-in-minio-storage"
    up = _upload(client, csrf_token, "encrypted.txt", plaintext, "text/plain")
    file_id = up.json["id"]

    record = db_session.scalar(select(File).where(File.id == uuid.UUID(file_id)))
    assert record is not None
    assert len(record.wrapped_dek) == 60  # nonce(12) + ct(32) + tag(16)
    assert len(record.nonce) == 12
    assert len(record.auth_tag) == 16
    assert record.kek_version >= 1

    response = storage.get(str(record.storage_key))
    try:
        on_disk = b"".join(response.stream(64 * 1024))
    finally:
        response.close()
        response.release_conn()

    assert on_disk != plaintext
    assert plaintext not in on_disk
    # Ciphertext length matches plaintext length (GCM is a stream cipher; tag stored separately).
    assert len(on_disk) == len(plaintext)


def test_download_other_users_file_returns_404(
    client, db_session, logged_in_admin, seeded_other_user
) -> None:
    other_file = File(
        owner_id=seeded_other_user.id,
        original_filename="theirs.bin",
        storage_key=uuid.uuid4(),
        mime_type="application/octet-stream",
        size_bytes=5,
        sha256="1" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(other_file)
    db_session.commit()
    response = client.get(f"/api/files/{other_file.id}/download")
    assert response.status_code == 404


def test_download_nonexistent_returns_404(client, db_session, logged_in_admin) -> None:
    response = client.get(f"/api/files/{uuid.uuid4()}/download")
    assert response.status_code == 404
