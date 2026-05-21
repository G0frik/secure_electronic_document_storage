"""File-version domain service (Phase 15).

The *current* version of every file lives in the `files` row — same shape
as before. Historical snapshots are kept in `file_versions`. The flow is:

  1. User uploads a new version (`upload_new_version`)
  2. Service quota-checks the new size
  3. Encrypts the new content; PUTs it to MinIO with a new storage_key
  4. SNAPSHOTS the existing `files` columns into a new `file_versions` row
     keyed by `version_number = files.current_version` (the *old* current)
  5. Overwrites `files` columns with the new content; bumps
     `files.current_version`
  6. Increments the owner's quota by the new size (the old version stays
     on disk and continues to count until the reaper or a manual delete
     removes it)
  7. Enqueues a fresh classification task (which reads from `files.*`,
     i.e. the new current content) — "per-version classification"

Downloads:
  * `stream_current_version` is the same as `files.stream_download`
  * `stream_specific_version` decrypts from a `FileVersion` row

Reaper:
  * `reap_expired_versions(retention_days=30)` removes historical (non-
    current) versions older than the cutoff — MinIO blob + DB row + quota
    decrement.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.file import File
from app.models.file_version import FileVersion
from app.models.user import User
from app.services import audit, classification, crypto, quota, storage

log = get_logger(__name__)

DEFAULT_VERSION_RETENTION_DAYS = 30
_DOWNLOAD_CHUNK_BYTES = 64 * 1024


class VersionUploadError(ValueError):
    """Catch-all for bad input on a version upload."""


class VersionNotFoundError(LookupError):
    """Caller asked for a version_number that doesn't exist for the file."""


@dataclass(frozen=True)
class VersionView:
    """Single row in the versions list — works for both current + historical."""

    version_number: int
    is_current: bool
    storage_key: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    kek_version: int
    uploader_id: uuid.UUID | None
    uploaded_at: datetime | None


# --- Helpers --------------------------------------------------------------


def _snapshot_current_into_versions(
    file_record: File, uploader_id: uuid.UUID | None
) -> FileVersion:
    """Copy the `files` row's content columns into a new `file_versions` row
    at `version_number = file_record.current_version`. Returns the inserted
    row.

    Called before overwriting `files` with new content.
    """
    snapshot = FileVersion(
        file_id=file_record.id,
        version_number=file_record.current_version,
        storage_key=file_record.storage_key,
        original_filename=file_record.original_filename,
        mime_type=file_record.mime_type,
        size_bytes=file_record.size_bytes,
        sha256=file_record.sha256,
        wrapped_dek=file_record.wrapped_dek,
        nonce=file_record.nonce,
        auth_tag=file_record.auth_tag,
        kek_version=file_record.kek_version,
        uploader_id=uploader_id,
        # Use the file's uploaded_at as a best-effort timestamp for the snapshot.
        # Subsequent overwrites bump files.uploaded_at = NOW().
        uploaded_at=file_record.uploaded_at,
    )
    db.session.add(snapshot)
    return snapshot


# --- Upload new version ---------------------------------------------------


def upload_new_version(
    *,
    file_record: File,
    uploaded: FileStorage,
    uploader: User,
) -> File:
    """Owner uploads a new version of `file_record`. Returns the same row
    (now mutated with the new content + bumped `current_version`).
    """
    if uploaded is None or not uploaded.filename:
        raise VersionUploadError("No file provided.")

    plaintext = uploaded.stream.read()
    new_size = len(plaintext)
    if new_size == 0:
        raise VersionUploadError("Uploaded file is empty.")

    # Phase 12 — quota check on the NEW version's size only. The old version
    # already counts toward the owner's used_bytes; we add the new on top
    # because the snapshot retains the old bytes until the reaper purges them.
    quota.check_quota_for_upload(uploader, new_size)

    sha256_hex = hashlib.sha256(plaintext).hexdigest()
    mime_type = uploaded.mimetype or "application/octet-stream"

    blob = crypto.encrypt_file(plaintext)
    new_storage_key = uuid.uuid4()
    storage.put(
        str(new_storage_key),
        io.BytesIO(blob.ciphertext),
        length=len(blob.ciphertext),
        content_type="application/octet-stream",
    )

    # 1. Snapshot current into history.
    snapshot = _snapshot_current_into_versions(file_record, uploader.id)

    # 2. Overwrite current with new content.
    file_record.storage_key = new_storage_key
    file_record.original_filename = uploaded.filename
    file_record.mime_type = mime_type
    file_record.size_bytes = new_size
    file_record.sha256 = sha256_hex
    file_record.wrapped_dek = blob.wrapped_dek
    file_record.nonce = blob.nonce
    file_record.auth_tag = blob.auth_tag
    file_record.kek_version = blob.kek_version
    file_record.uploaded_at = datetime.now(timezone.utc)
    file_record.current_version = file_record.current_version + 1

    # 3. Quota — new bytes on top of existing.
    quota.increment_used(uploader, new_size)

    # 4. Per-version classification — fresh PENDING row at version=MAX+1.
    #    `get_latest` already orders by version desc, so the policy check
    #    automatically picks up the new tier once classification finishes.
    classification.create_pending(file_record.id, commit=False)

    audit.record(
        "file.version_uploaded",
        actor=uploader,
        target_type="file",
        target_id=file_record.id,
        metadata={
            "filename": uploaded.filename,
            "size_bytes": new_size,
            "mime_type": mime_type,
            "sha256": sha256_hex,
            "new_version": file_record.current_version,
            "snapshot_version": snapshot.version_number,
            "kek_version": blob.kek_version,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()

    # 5. Re-classify the file. The classifier reads from files.storage_key
    #    which now points at the new content.
    from app.tasks.classification import classify_file  # lazy import

    classify_file.delay(str(file_record.id))

    return file_record


# --- Listing --------------------------------------------------------------


def list_versions(file_record: File) -> list[VersionView]:
    """All versions of the file, current first.

    Combines the current `files` row (as `is_current=True`) with every
    `file_versions` snapshot for the same file_id.
    """
    history = list(
        db.session.scalars(
            select(FileVersion)
            .where(FileVersion.file_id == file_record.id)
            .order_by(FileVersion.version_number.desc())
        )
    )
    current = VersionView(
        version_number=file_record.current_version,
        is_current=True,
        storage_key=file_record.storage_key,
        original_filename=file_record.original_filename,
        mime_type=file_record.mime_type,
        size_bytes=file_record.size_bytes,
        sha256=file_record.sha256,
        kek_version=file_record.kek_version,
        uploader_id=file_record.owner_id,
        uploaded_at=file_record.uploaded_at,
    )
    historical = [
        VersionView(
            version_number=v.version_number,
            is_current=False,
            storage_key=v.storage_key,
            original_filename=v.original_filename,
            mime_type=v.mime_type,
            size_bytes=v.size_bytes,
            sha256=v.sha256,
            kek_version=v.kek_version,
            uploader_id=v.uploader_id,
            uploaded_at=v.uploaded_at,
        )
        for v in history
    ]
    return [current, *historical]


# --- Downloads ------------------------------------------------------------


def get_version(
    file_record: File, version_number: int
) -> tuple[bool, FileVersion | None]:
    """Resolve a version number for the file.

    Returns (is_current, FileVersion|None):
      * (True, None) if `version_number == file_record.current_version`
      * (False, row) if a historical snapshot exists
      * raises VersionNotFoundError otherwise
    """
    if version_number == file_record.current_version:
        return True, None
    row = db.session.scalar(
        select(FileVersion).where(
            FileVersion.file_id == file_record.id,
            FileVersion.version_number == version_number,
        )
    )
    if row is None:
        raise VersionNotFoundError(
            f"Version {version_number} not found for file {file_record.id}"
        )
    return False, row


def stream_version_download(
    file_record: File,
    version: FileVersion,
    *,
    actor: User | None,
) -> Iterator[bytes]:
    """Decrypt + stream a HISTORICAL version's bytes.

    Writes a `file.version_downloaded` audit row BEFORE streaming. Same
    integrity guarantee as `files.stream_download`: AES-GCM tag verified
    before any plaintext leaves the function.
    """
    audit.record(
        "file.version_downloaded",
        actor=actor,
        target_type="file",
        target_id=file_record.id,
        metadata={
            "filename": version.original_filename,
            "size_bytes": version.size_bytes,
            "version_number": version.version_number,
            "is_current": False,
        },
        severity=AuditSeverity.INFO,
    )

    response = storage.get(str(version.storage_key))
    try:
        ciphertext = b"".join(response.stream(_DOWNLOAD_CHUNK_BYTES))
    finally:
        response.close()
        response.release_conn()

    plaintext = crypto.decrypt_file(
        ciphertext=ciphertext,
        wrapped_dek=version.wrapped_dek,
        nonce=version.nonce,
        auth_tag=version.auth_tag,
        kek_version=version.kek_version,
    )

    def chunks() -> Iterator[bytes]:
        for offset in range(0, len(plaintext), _DOWNLOAD_CHUNK_BYTES):
            yield plaintext[offset : offset + _DOWNLOAD_CHUNK_BYTES]

    return chunks()


# --- Deletion (single version) -------------------------------------------


def delete_version(
    file_record: File,
    version: FileVersion,
    *,
    actor: User | None,
    reason: str = "user",
) -> None:
    """Hard-delete one HISTORICAL version. Refuses to delete the current
    one (callers should call `trash.hard_delete` on the file instead).

    Order: drop DB row + decrement quota → remove MinIO blob (best-effort).
    """
    if version.file_id != file_record.id:
        raise VersionNotFoundError("Version does not belong to this file.")

    storage_key = str(version.storage_key)
    size = version.size_bytes
    version_number = version.version_number

    owner = db.session.get(User, file_record.owner_id)
    if owner is not None:
        quota.decrement_used(owner, size)

    db.session.delete(version)
    db.session.commit()

    try:
        storage.delete(storage_key)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "file_versions.minio_delete_failed",
            file_id=str(file_record.id),
            version_number=version_number,
            storage_key=storage_key,
            error=str(exc),
        )

    audit.record(
        "file.version_deleted",
        actor=actor,
        target_type="file",
        target_id=file_record.id,
        metadata={
            "version_number": version_number,
            "size_bytes": size,
            "reason": reason,
            "storage_key": storage_key,
        },
        severity=AuditSeverity.INFO,
    )


# --- Reaper ---------------------------------------------------------------


def reap_expired_versions(
    *,
    retention_days: int = DEFAULT_VERSION_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Hard-delete every historical version older than the cutoff. Current
    versions (which live in the `files` row, NOT here) are never touched.

    Returns the count of versions removed.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    expired = list(
        db.session.scalars(
            select(FileVersion).where(FileVersion.uploaded_at < cutoff)
        )
    )
    removed = 0
    for version in expired:
        file_record = db.session.get(File, version.file_id)
        if file_record is None:
            # File was hard-deleted in the meantime; FK cascade should have
            # removed this row, but be defensive.
            db.session.delete(version)
            db.session.commit()
            removed += 1
            continue
        delete_version(
            file_record, version, actor=None, reason=f"reaper>{retention_days}d"
        )
        removed += 1

    audit.record(
        "file.versions_reaped",
        target_type="system",
        metadata={
            "count": removed,
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
        },
        severity=AuditSeverity.INFO,
    )
    return removed
