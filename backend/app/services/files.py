"""File domain service. All file state changes go through here."""

from __future__ import annotations

import hashlib
import tempfile
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
from app.services import audit, storage

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


def create_from_upload(*, owner: User, uploaded: FileStorage) -> File:
    """Persist an uploaded file: stream → MinIO + DB row + audit."""
    if uploaded is None or not uploaded.filename:
        raise EmptyUploadError("No file provided.")

    storage_key = uuid.uuid4()
    sha = hashlib.sha256()
    size = 0

    # Spooled buffer keeps small files in RAM, spills large ones to disk.
    # Phase 0 cap is 50 MB so the threshold here is mostly cosmetic.
    with tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024) as buf:
        while True:
            chunk = uploaded.stream.read(64 * 1024)
            if not chunk:
                break
            sha.update(chunk)
            size += len(chunk)
            buf.write(chunk)

        if size == 0:
            raise EmptyUploadError("Uploaded file is empty.")

        buf.seek(0)
        mime_type = uploaded.mimetype or "application/octet-stream"
        storage.put(str(storage_key), buf, length=size, content_type=mime_type)

    file_record = File(
        owner_id=owner.id,
        original_filename=uploaded.filename,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size,
        sha256=sha.hexdigest(),
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
        },
        commit=False,
    )
    db.session.commit()
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
    """Stream the file bytes from MinIO. Audits 'file.downloaded' before streaming."""
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

    def chunks() -> Iterator[bytes]:
        try:
            for chunk in response.stream(64 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    return chunks()


def delete_orphan_storage(record: File) -> None:
    """Remove the MinIO object. Caller is responsible for the DB row.

    Not used in Phase 2 — wired up for Phase 9 (trash hard-delete) and tests.
    """
    storage.delete(str(record.storage_key))
    audit.record(
        "file.storage_removed",
        target_type="file",
        target_id=record.id,
        severity=AuditSeverity.INFO,
        metadata={"storage_key": str(record.storage_key)},
    )
