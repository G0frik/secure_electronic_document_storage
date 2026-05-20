"""Share domain service — additive grants of access on top of RBAC.

Phase 7. Cloud-drive semantics: when the owner shares a file or folder
with a recipient, the recipient gains real read access to that resource,
overriding the tier ceiling in their default policy. Admin override and
ownership short-circuits still apply, and the standard category denies
in policy continue to bite (sharing a `denied_category` is still blocked).

A share is polymorphic over (file | folder). Folder shares propagate
recursively to every descendant file at query time — no rows are
materialised per file.

Lifecycle: create → revoke (soft, sets `revoked_at`). The partial unique
index on (target_type, target_id, recipient_id) WHERE revoked_at IS NULL
ensures at most one *active* share per (target, recipient); historic
revoked rows are kept for audit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.logging_config import get_logger
from app.models.file import File
from app.models.folder import Folder
from app.models.share import Share, SharePermission, ShareTargetType
from app.models.user import User
from app.services import audit, folders, users

log = get_logger(__name__)


# --- Errors ---


class ShareError(Exception):
    """Base class for share creation/revocation failures."""


class SharePermissionDeniedError(ShareError):
    """Caller is not the granter or admin."""


class ShareTargetNotFoundError(ShareError):
    """Target file/folder doesn't exist (or caller doesn't own it)."""


class ShareRecipientNotFoundError(ShareError):
    """Recipient email not found / inactive."""


class ShareAlreadyExistsError(ShareError):
    """Active share for (target, recipient) already exists."""


class ShareSelfError(ShareError):
    """Cannot share with yourself."""


# --- Read helpers ---


@dataclass(frozen=True)
class SharedFileEntry:
    """One file the user reaches via a share. Multiple share paths collapse
    into one entry; the *closest* share (file > folder ancestor) wins for
    the displayed permission.
    """

    file: File
    share: Share
    via_folder_id: uuid.UUID | None  # NULL when the share is directly on the file


def get_share(share_id: uuid.UUID) -> Share | None:
    return db.session.get(Share, share_id)


def list_received(user: User) -> list[Share]:
    """Active shares whose recipient is *user*."""
    return list(
        db.session.scalars(
            select(Share)
            .where(Share.recipient_id == user.id, Share.revoked_at.is_(None))
            .order_by(Share.created_at.desc())
        )
    )


def list_granted(user: User) -> list[Share]:
    """Active shares the user created. Revoked rows are excluded."""
    return list(
        db.session.scalars(
            select(Share)
            .where(Share.granter_id == user.id, Share.revoked_at.is_(None))
            .order_by(Share.created_at.desc())
        )
    )


# --- Access lookup (called by policy.py) ---


def active_shares_for_recipient(recipient: User) -> list[Share]:
    return list(
        db.session.scalars(
            select(Share).where(
                Share.recipient_id == recipient.id, Share.revoked_at.is_(None)
            )
        )
    )


def user_has_share_access(recipient: User, file: File) -> Share | None:
    """Return the matching active Share if *recipient* reaches *file* via any
    active share (direct on file OR on any of its folder ancestors). Return
    None if no such share exists.

    Trashed files (Phase 9) are NOT reachable via shares — the share row may
    still exist, but `file.deleted_at IS NOT NULL` blocks the grant. The
    file becomes share-accessible again automatically on restore.
    """
    if file.deleted_at is not None:
        return None
    received = active_shares_for_recipient(recipient)
    if not received:
        return None

    # Direct file share.
    for share in received:
        if share.target_type == ShareTargetType.FILE and share.target_id == file.id:
            return share

    # Folder-share walk-up. file.folder_id may be NULL (root); only resolve
    # the ancestor chain if the file is in a folder.
    if file.folder_id is None:
        return None
    ancestor_chain = set(folders.ancestor_folder_ids(file.folder_id))
    for share in received:
        if share.target_type == ShareTargetType.FOLDER and share.target_id in ancestor_chain:
            return share
    return None


def accessible_file_ids_via_shares(recipient: User) -> set[uuid.UUID]:
    """All file IDs reachable by *recipient* through any active share.

    Used by the listing endpoint to build the "shared with me" view in one
    query batch (no per-file walk).
    """
    received = active_shares_for_recipient(recipient)
    if not received:
        return set()

    file_ids: set[uuid.UUID] = set()
    folder_roots: list[uuid.UUID] = []
    for share in received:
        if share.target_type == ShareTargetType.FILE:
            file_ids.add(share.target_id)
        else:
            folder_roots.append(share.target_id)

    if folder_roots:
        # Walk DOWN: every descendant folder of any shared folder root.
        reachable_folders = folders.descendant_folder_ids(folder_roots)
        for file_obj in folders.files_in_folders(reachable_folders):
            if file_obj.deleted_at is None:
                file_ids.add(file_obj.id)

    return file_ids


# --- Mutations ---


def create_share(
    *,
    granter: User,
    target_type: ShareTargetType,
    target_id: uuid.UUID,
    recipient_email: str,
    permission: SharePermission = SharePermission.VIEWER,
) -> Share:
    """Create an active share. Granter must own the target (admin may share
    any target). Reactivates a previously revoked share for the same
    (target, recipient) rather than inserting a duplicate row.
    """
    recipient = users.get_user_by_email(recipient_email)
    if recipient is None or not recipient.is_active:
        raise ShareRecipientNotFoundError(f"No active user with email {recipient_email!r}.")
    if recipient.id == granter.id:
        raise ShareSelfError("Cannot share with yourself.")

    _check_target_grantable(granter, target_type, target_id)

    # Reactivate-or-create. We hold a SAVEPOINT around the insert so a
    # concurrent attempt can be retried as an UPDATE.
    existing = db.session.scalar(
        select(Share).where(
            Share.target_type == target_type,
            Share.target_id == target_id,
            Share.recipient_id == recipient.id,
        ).order_by(Share.created_at.desc())
    )

    if existing is not None and existing.revoked_at is None:
        raise ShareAlreadyExistsError("This share already exists.")

    if existing is not None and existing.revoked_at is not None:
        # Reactivate the most recent revoked row in place.
        existing.revoked_at = None
        existing.permission = permission
        existing.created_at = datetime.now(timezone.utc)
        share = existing
    else:
        share = Share(
            target_type=target_type,
            target_id=target_id,
            granter_id=granter.id,
            recipient_id=recipient.id,
            permission=permission,
        )
        db.session.add(share)

    try:
        db.session.flush()
    except IntegrityError as exc:
        db.session.rollback()
        raise ShareAlreadyExistsError("This share already exists.") from exc

    audit.record(
        "share.created",
        actor=granter,
        target_type=target_type.value,
        target_id=target_id,
        metadata={
            "share_id": str(share.id),
            "recipient_id": str(recipient.id),
            "recipient_email": recipient.email,
            "permission": permission.value,
        },
        commit=False,
    )
    db.session.commit()
    return share


def revoke_share(share: Share, *, actor: User) -> None:
    """Soft-revoke a share. Granter or admin may revoke."""
    if not (actor.is_admin or actor.id == share.granter_id):
        raise SharePermissionDeniedError(
            "Only the granter or an admin can revoke this share."
        )
    if share.revoked_at is not None:
        return  # idempotent

    share.revoked_at = datetime.now(timezone.utc)
    audit.record(
        "share.revoked",
        actor=actor,
        target_type=share.target_type.value,
        target_id=share.target_id,
        metadata={
            "share_id": str(share.id),
            "recipient_id": str(share.recipient_id),
            "permission": share.permission.value,
        },
        commit=False,
    )
    db.session.commit()


# --- Internals ---


def _check_target_grantable(
    granter: User, target_type: ShareTargetType, target_id: uuid.UUID
) -> None:
    """Verify the target exists and the granter is allowed to share it."""
    if target_type == ShareTargetType.FILE:
        record = db.session.get(File, target_id)
        if record is None:
            raise ShareTargetNotFoundError("File not found.")
        if record.owner_id != granter.id and not granter.is_admin:
            raise ShareTargetNotFoundError("You may only share files you own.")
        return

    if target_type == ShareTargetType.FOLDER:
        folder = db.session.get(Folder, target_id)
        if folder is None:
            raise ShareTargetNotFoundError("Folder not found.")
        if folder.owner_id != granter.id and not granter.is_admin:
            raise ShareTargetNotFoundError("You may only share folders you own.")
        return

    raise ShareTargetNotFoundError(f"Unknown target type {target_type!r}.")
