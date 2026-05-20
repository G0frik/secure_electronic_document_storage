"""Phase 7 — /api/folders/* CRUD."""

from __future__ import annotations

import io
import uuid

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.file import File
from app.models.folder import Folder


def _create_folder(client, csrf_token, name, parent_id=None):
    return client.post(
        "/api/folders",
        json={"name": name, "parent_id": str(parent_id) if parent_id else None},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )


# --- Create ---


def test_create_folder_requires_auth(client, csrf_token) -> None:
    resp = _create_folder(client, csrf_token, "x")
    assert resp.status_code == 401


def test_create_root_folder(client, db_session, logged_in_admin, csrf_token) -> None:
    resp = _create_folder(client, csrf_token, "Quarterlies")
    assert resp.status_code == 201, resp.data
    assert resp.json["name"] == "Quarterlies"
    assert resp.json["parent_id"] is None

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "folder.created")
    ).all()
    assert len(audits) == 1


def test_create_nested_folder(client, db_session, logged_in_admin, csrf_token) -> None:
    parent = _create_folder(client, csrf_token, "HR").json
    child = _create_folder(client, csrf_token, "Payroll", parent_id=parent["id"]).json
    assert child["parent_id"] == parent["id"]


def test_duplicate_folder_in_same_parent_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    _create_folder(client, csrf_token, "Same")
    dup = _create_folder(client, csrf_token, "Same")
    assert dup.status_code == 409


def test_same_name_in_different_parents_is_ok(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    a = _create_folder(client, csrf_token, "A").json
    b = _create_folder(client, csrf_token, "B").json
    _create_folder(client, csrf_token, "Reports", parent_id=a["id"])
    resp = _create_folder(client, csrf_token, "Reports", parent_id=b["id"])
    assert resp.status_code == 201


def test_create_with_unknown_parent_is_400(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    resp = _create_folder(client, csrf_token, "x", parent_id=uuid.uuid4())
    assert resp.status_code == 400
    assert resp.json["error"] == "invalid_parent"


def test_create_with_other_users_parent_is_400(
    client, db_session, logged_in_user, seeded_admin, csrf_token
) -> None:
    """The parent must belong to the caller — even an existing folder owned by
    someone else must be rejected (anti-information-leak)."""
    other_folder = Folder(owner_id=seeded_admin.id, name="Other root")
    db_session.add(other_folder)
    db_session.commit()
    resp = _create_folder(client, csrf_token, "x", parent_id=other_folder.id)
    assert resp.status_code == 400


def test_create_rejects_blank_name(client, db_session, logged_in_admin, csrf_token) -> None:
    resp = _create_folder(client, csrf_token, "   ")
    # Pydantic blocks fully empty; whitespace-only goes through to service and
    # comes back as invalid_request.
    assert resp.status_code in (400, 422)


# --- List / get ---


def test_list_folders_returns_own_only(
    client, db_session, logged_in_admin, csrf_token, seeded_other_user
) -> None:
    _create_folder(client, csrf_token, "Mine")
    other_folder = Folder(owner_id=seeded_other_user.id, name="Theirs")
    db_session.add(other_folder)
    db_session.commit()

    resp = client.get("/api/folders")
    assert resp.status_code == 200
    names = {f["name"] for f in resp.json["items"]}
    assert "Mine" in names
    assert "Theirs" not in names


def test_get_folder_404_for_unknown(client, db_session, logged_in_admin) -> None:
    resp = client.get(f"/api/folders/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_other_users_folder_returns_404(
    client, db_session, logged_in_admin, seeded_other_user
) -> None:
    folder = Folder(owner_id=seeded_other_user.id, name="Theirs")
    db_session.add(folder)
    db_session.commit()
    resp = client.get(f"/api/folders/{folder.id}")
    assert resp.status_code == 404


# --- Delete ---


def test_delete_empty_folder(client, db_session, logged_in_admin, csrf_token) -> None:
    folder = _create_folder(client, csrf_token, "Empty").json
    resp = client.delete(
        f"/api/folders/{folder['id']}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 204
    assert db_session.get(Folder, uuid.UUID(folder["id"])) is None


def test_delete_folder_with_subfolders_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    parent = _create_folder(client, csrf_token, "Parent").json
    _create_folder(client, csrf_token, "Child", parent_id=parent["id"])
    resp = client.delete(
        f"/api/folders/{parent['id']}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 409


def test_delete_folder_with_files_is_409(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    folder = _create_folder(client, csrf_token, "WithFile").json
    # Place a file in the folder directly via the model (no upload roundtrip).
    f = File(
        owner_id=logged_in_admin.id,
        folder_id=uuid.UUID(folder["id"]),
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

    resp = client.delete(
        f"/api/folders/{folder['id']}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 409


# --- Upload integration ---


def test_upload_into_folder(client, db_session, logged_in_admin, csrf_token) -> None:
    folder = _create_folder(client, csrf_token, "Drop zone").json
    resp = client.post(
        "/api/files",
        data={
            "file": (io.BytesIO(b"hello"), "x.txt", "text/plain"),
            "folder_id": folder["id"],
        },
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.data
    assert resp.json["folder_id"] == folder["id"]


def test_upload_into_unknown_folder_is_400(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    resp = client.post(
        "/api/files",
        data={
            "file": (io.BytesIO(b"hello"), "x.txt", "text/plain"),
            "folder_id": str(uuid.uuid4()),
        },
        headers={"X-CSRF-Token": csrf_token},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_list_files_filter_by_folder(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    folder = _create_folder(client, csrf_token, "Inside").json
    # One file inside the folder, one at root.
    for body, name, fid in [(b"a", "inside.txt", folder["id"]), (b"b", "root.txt", None)]:
        client.post(
            "/api/files",
            data={
                "file": (io.BytesIO(body), name, "text/plain"),
                **({"folder_id": fid} if fid else {}),
            },
            headers={"X-CSRF-Token": csrf_token},
            content_type="multipart/form-data",
        )

    listing_root = client.get("/api/files?folder_scope=folder").json
    listing_folder = client.get(
        f"/api/files?folder_scope=folder&folder_id={folder['id']}"
    ).json
    listing_all = client.get("/api/files").json

    assert {f["original_filename"] for f in listing_root["items"]} == {"root.txt"}
    assert {f["original_filename"] for f in listing_folder["items"]} == {"inside.txt"}
    assert {f["original_filename"] for f in listing_all["items"]} == {"inside.txt", "root.txt"}
