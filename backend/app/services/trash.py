"""Trash domain service — soft delete, restore, hard delete (Phase 9).

Soft delete flips `File.deleted_at` to `now()`. Listings everywhere filter
that out, so the row disappears from My Files / Shared with me / share-link
landings without losing any data.

Restore unsets `deleted_at`. If the file's parent folder has been removed
in the meantime, the file is moved to root (same UX as Google Drive).

Hard delete physically removes the ciphertext from MinIO + cascades through
classifications and share-links via the FK ON DELETE CASCADE we set in
phases 4/8. Internal Share rows (Phase 7) are polymorphic and have no FK,
so we explicitly delete them here.

The reaper (`reap_expired_trash`) is called by a Celery task and a Flask
CLI command. Default retention: 30 days from `deleted_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.file import File
from app.models.share import Share, ShareTargetType
from app.models.user import User
from app.services import audit, quota, storage

log = get_logger(__name__)

DEFAULT_RETENTION_DAYS = 30


class TrashError(Exception):
    """Base class for trash failures."""


class FileNotInTrashError(TrashError):
    """Tried to restore/hard-delete a file that isn't in the trash."""


# --- Soft delete (the user clicks Delete on a live file) ---


def soft_delete(file: File, *, actor: User) -> None:
    """Move *file* to the user's trash. Idempotent on already-trashed rows."""
    if file.deleted_at is not None:
        return
    file.deleted_at = datetime.now(timezone.utc)
    audit.record(
        "file.soft_deleted",
        actor=actor,
        target_type="file",
        target_id=file.id,
        metadata={
            "filename": file.original_filename,
            "size_bytes": file.size_bytes,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()


# --- Trash listing + restore + hard-delete-now ---


def list_trashed_for_owner(owner: User) -> list[File]:
    """All of *owner*'s soft-deleted files, newest-first by deletion time."""
    return list(
        db.session.scalars(
            select(File)
            .where(File.owner_id == owner.id, File.deleted_at.is_not(None))
            .order_by(File.deleted_at.desc())
        )
    )


def restore(file: File, *, actor: User) -> File:
    """Bring *file* back to live. If its parent folder is gone, drop the
    folder_id so the restored file lands at root (Google Drive semantics).
    """
    if file.deleted_at is None:
        raise FileNotInTrashError("File is not in the trash.")

    from app.models.folder import Folder

    parent_gone = False
    if file.folder_id is not None:
        parent = db.session.get(Folder, file.folder_id)
        if parent is None or parent.deleted_at is not None:
            file.folder_id = None
            parent_gone = True

    file.deleted_at = None
    audit.record(
        "file.restored",
        actor=actor,
        target_type="file",
        target_id=file.id,
        metadata={
            "filename": file.original_filename,
            "parent_folder_lost": parent_gone,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return file


def hard_delete(file: File, *, actor: User | None = None, reason: str = "user") -> None:
    """Physically remove the file. Caller's responsibility to verify
    permissions before invoking (i.e. owner or admin).

    Cleanup ordering:
      1. Detach shares (Phase 7) — polymorphic, no FK.
      2. Drop the SQLAlchemy row — classifications + share_links cascade.
      3. Remove the ciphertext blob from MinIO.

    MinIO deletion happens last so a DB rollback leaves the bytes intact;
    leaking a ciphertext object is safer than orphaning a DB row with no
    way to decrypt it.
    """
    file_id = file.id
    storage_key = str(file.storage_key)
    filename = file.original_filename
    size = file.size_bytes
    owner_id = file.owner_id

    # 1. Detach polymorphic shares.
    db.session.execute(
        Share.__table__.delete().where(
            Share.target_type == ShareTargetType.FILE,
            Share.target_id == file_id,
        )
    )

    # 2. Drop the row (classifications + share_links cascade via FK) and
    #    free quota space on the owner. Trash counted toward quota; hard-
    #    delete is the only operation that gives bytes back.
    owner = db.session.get(User, owner_id)
    quota.decrement_used(owner, size)
    db.session.delete(file)
    db.session.commit()

    # 3. MinIO best-effort.
    try:
        storage.delete(storage_key)
    except Exception as exc:  # noqa: BLE001 - want to log + continue
        log.warning(
            "trash.minio_delete_failed",
            file_id=str(file_id),
            storage_key=storage_key,
            error=str(exc),
        )

    audit.record(
        "file.hard_deleted",
        actor=actor,
        target_type="file",
        target_id=file_id,
        metadata={
            "filename": filename,
            "size_bytes": size,
            "storage_key": storage_key,
            "reason": reason,
        },
        severity=AuditSeverity.WARNING,
    )


# --- Reaper (called by Celery / flask CLI) ---


def reap_expired_trash(
    *, retention_days: int = DEFAULT_RETENTION_DAYS, now: datetime | None = None
) -> int:
    """Hard-delete every file whose `deleted_at` is older than the cutoff.
    Returns the count of files removed.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    expired = list(
        db.session.scalars(
            select(File).where(
                File.deleted_at.is_not(None), File.deleted_at < cutoff
            )
        )
    )
    for file in expired:
        hard_delete(file, actor=None, reason=f"reaper>{retention_days}d")

    audit.record(
        "trash.reaped",
        target_type="system",
        metadata={
            "count": len(expired),
            "retention_days": retention_days,
            "cutoff": cutoff.isoformat(),
        },
        severity=AuditSeverity.INFO,
    )
    return len(expired)
