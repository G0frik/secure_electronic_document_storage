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


def create_from_upload(*, owner: User, uploaded: FileStorage) -> File:
    """Persist an uploaded file: encrypt → MinIO + DB row + audit.

    Memory note: we read the entire upload into memory to compute SHA-256
    AND to run AES-256-GCM (which needs the full plaintext at once for the
    auth tag). Bounded by `MAX_CONTENT_LENGTH` (50 MB in dev).
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
    """Return the file IF the owner owns it; otherwise raise FileNotFoundError."""
    record = db.session.scalar(
        select(File).where(File.id == file_id, File.owner_id == owner.id)
    )
    if record is None:
        raise FileNotFoundError(str(file_id))
    return record


def list_for_owner(owner: User, *, page: int, per_page: int) -> FileListing:
    base = select(File).where(File.owner_id == owner.id)
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
        metadata={"page": page, "per_page": per_page, "count": len(items), "total": total},
    )
    return FileListing(items=items, total=total, page=page, per_page=per_page)


def stream_download(record: File, *, actor: User) -> Iterator[bytes]:
    """Decrypt + stream the file. Audits 'file.downloaded' BEFORE streaming.

    Implementation: fetch ciphertext from MinIO, decrypt the whole blob
    (AES-GCM needs the full ciphertext to verify the tag), then yield
    plaintext in fixed-size chunks. No unauthenticated bytes ever leave
    this function — the tag is verified before we yield anything.
    """
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
