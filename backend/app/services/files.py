"""File domain service. All file state changes go through here."""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import func, select
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.file import File
from app.models.user import User
from app.services import audit, classification, crypto, storage

log = get_logger(__name__)


class FileNotFoundError(LookupError):
    """File doesn't exist OR caller doesn't own it (we don't distinguish — anti-enumeration)."""


class EmptyUploadError(ValueError):
    """Uploaded file is empty or missing."""


@dataclass
class FileListing:
    items: list[File]
    total: int
    page: int
    per_page: int


_DOWNLOAD_CHUNK_BYTES = 64 * 1024


def create_from_upload(
    *,
    owner: User,
    uploaded: FileStorage,
    folder_id: uuid.UUID | None = None,
) -> File:
    """Persist an uploaded file: encrypt → MinIO + DB row + audit.

    Memory note: we read the entire upload into memory to compute SHA-256
    AND to run AES-256-GCM (which needs the full plaintext at once for the
    auth tag). Bounded by `MAX_CONTENT_LENGTH` (50 MB in dev).

    Optional `folder_id` puts the file in a folder; the caller is
    responsible for verifying the folder belongs to *owner* before calling.
    """
    if uploaded is None or not uploaded.filename:
        raise EmptyUploadError("No file provided.")

    plaintext = uploaded.stream.read()
    size = len(plaintext)
    if size == 0:
        raise EmptyUploadError("Uploaded file is empty.")

    sha256_hex = hashlib.sha256(plaintext).hexdigest()
    mime_type = uploaded.mimetype or "application/octet-stream"

    blob = crypto.encrypt_file(plaintext)
    storage_key = uuid.uuid4()
    storage.put(
        str(storage_key),
        io.BytesIO(blob.ciphertext),
        length=len(blob.ciphertext),
        # Ciphertext is opaque — never advertise the real mime type to MinIO.
        content_type="application/octet-stream",
    )

    file_record = File(
        owner_id=owner.id,
        folder_id=folder_id,
        original_filename=uploaded.filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size,
        sha256=sha256_hex,
        wrapped_dek=blob.wrapped_dek,
        nonce=blob.nonce,
        auth_tag=blob.auth_tag,
        kek_version=blob.kek_version,
    )
    db.session.add(file_record)
    db.session.flush()

    audit.record(
        "file.uploaded",
        actor=owner,
        target_type="file",
        target_id=file_record.id,
        metadata={
            "filename": uploaded.filename,
            "size_bytes": size,
            "mime_type": mime_type,
            "sha256": file_record.sha256,
            "kek_version": blob.kek_version,
        },
        commit=False,
    )

    # Phase 4: insert PENDING Classification row alongside the file commit,
    # then enqueue the worker task AFTER commit so the worker sees both rows.
    classification.create_pending(file_record.id, commit=False)
    db.session.commit()

    from app.tasks.classification import classify_file  # lazy import

    classify_file.delay(str(file_record.id))

    return file_record


def get_for_owner(file_id: uuid.UUID, owner: User) -> File:
    """Return the file IF the owner owns it; otherwise raise FileNotFoundError.

    Used by code paths that should NEVER serve non-owned files (e.g. upload-time
    self-reference). Endpoints that need to honour Phase 5 RBAC should use
    `get_by_id` + `services.policy.can_user_access` instead.
    """
    record = db.session.scalar(
        select(File).where(File.id == file_id, File.owner_id == owner.id)
    )
    if record is None:
        raise FileNotFoundError(str(file_id))
    return record


def get_by_id(file_id: uuid.UUID) -> File | None:
    """Plain lookup — no ownership filter. Caller MUST run the policy check."""
    return db.session.scalar(select(File).where(File.id == file_id))


def list_for_owner(
    owner: User,
    *,
    page: int,
    per_page: int,
    folder_id: uuid.UUID | None = None,
    folder_scope: str = "all",
) -> FileListing:
    """List files the *owner* owns.

    `folder_scope`:
      - "all": every file the owner has, regardless of folder. Default.
      - "folder": files whose `folder_id == folder_id` (None = root level).
    """
    base = select(File).where(File.owner_id == owner.id)
    if folder_scope == "folder":
        if folder_id is None:
            base = base.where(File.folder_id.is_(None))
        else:
            base = base.where(File.folder_id == folder_id)

    total = (
        db.session.scalar(select(func.count()).select_from(base.subquery())) or 0
    )
    items = list(
        db.session.scalars(
            base.order_by(File.uploaded_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
    )
    audit.record(
        "file.listed",
        actor=owner,
        metadata={
            "page": page,
            "per_page": per_page,
            "count": len(items),
            "total": total,
            "folder_scope": folder_scope,
            "folder_id": str(folder_id) if folder_id else None,
        },
    )
    return FileListing(items=items, total=total, page=page, per_page=per_page)


def list_shared_with(user: User) -> list[File]:
    """Files the user reaches via active shares (direct or folder). Filtered
    through Phase 5 policy so denied entries (e.g., category blocks) don't
    leak into the response.
    """
    from app.services import policy, shares

    file_ids = shares.accessible_file_ids_via_shares(user)
    if not file_ids:
        return []
    records = list(db.session.scalars(select(File).where(File.id.in_(file_ids))))
    # Honour policy: shared files denied by a category rule are filtered out.
    visible = [
        f
        for f in records
        if policy.can_user_access(user, f, record=False).allowed
    ]
    visible.sort(key=lambda f: f.uploaded_at or _epoch(), reverse=True)
    return visible


def _epoch():  # type: ignore[no-untyped-def]
    from datetime import datetime, timezone

    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def stream_download(
    record: File,
    *,
    actor: User | None,
    emit_audit: bool = True,
) -> Iterator[bytes]:
    """Decrypt + stream the file. Audits 'file.downloaded' BEFORE streaming.

    Implementation: fetch ciphertext from MinIO, decrypt the whole blob
    (AES-GCM needs the full ciphertext to verify the tag), then yield
    plaintext in fixed-size chunks. No unauthenticated bytes ever leave
    this function — the tag is verified before we yield anything.

    `emit_audit=False` skips the `file.downloaded` event so public share-link
    downloads can write their more specific `share_link.downloaded` event
    instead (caller's responsibility).
    """
    if emit_audit:
        audit.record(
            "file.downloaded",
            actor=actor,
            target_type="file",
            target_id=record.id,
            metadata={
                "filename": record.original_filename,
                "size_bytes": record.size_bytes,
            },
        )

    response = storage.get(str(record.storage_key))
    try:
        ciphertext = b"".join(response.stream(_DOWNLOAD_CHUNK_BYTES))
    finally:
        response.close()
        response.release_conn()

    plaintext = crypto.decrypt_file(
        ciphertext=ciphertext,
        wrapped_dek=record.wrapped_dek,
        nonce=record.nonce,
        auth_tag=record.auth_tag,
        kek_version=record.kek_version,
    )

    def chunks() -> Iterator[bytes]:
        for offset in range(0, len(plaintext), _DOWNLOAD_CHUNK_BYTES):
            yield plaintext[offset : offset + _DOWNLOAD_CHUNK_BYTES]

    return chunks()


def delete_orphan_storage(record: File) -> None:
    """Remove the MinIO object. Caller is responsible for the DB row.

    Not used in Phase 2/3 — wired up for Phase 9 (trash hard-delete) and tests.
    """
    storage.delete(str(record.storage_key))
    audit.record(
        "file.storage_removed",
        target_type="file",
        target_id=record.id,
        severity=AuditSeverity.INFO,
        metadata={"storage_key": str(record.storage_key)},
    )
