"""Folder domain service.

Phase 7. Folders are pure metadata — owned by a user, optionally nested
under a parent folder of the same owner. Used as the unit of shareable
group access (see [services/shares.py]).
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.logging_config import get_logger
from app.models.file import File
from app.models.folder import Folder
from app.models.user import User
from app.services import audit

log = get_logger(__name__)


class FolderNotFoundError(LookupError):
    """Folder doesn't exist OR caller doesn't own it (anti-enumeration)."""


class FolderConflictError(ValueError):
    """Duplicate folder name in the same (owner, parent) scope."""


class FolderNotEmptyError(ValueError):
    """Refusing to delete a folder that still has files or subfolders."""


class InvalidParentError(ValueError):
    """Parent folder belongs to a different user, doesn't exist, or would create a cycle."""


def get_folder(folder_id: uuid.UUID) -> Folder | None:
    """Plain lookup. Use `get_for_owner` when the caller MUST own the folder."""
    return db.session.get(Folder, folder_id)


def get_for_owner(folder_id: uuid.UUID, owner: User) -> Folder:
    folder = db.session.scalar(
        select(Folder).where(Folder.id == folder_id, Folder.owner_id == owner.id)
    )
    if folder is None:
        raise FolderNotFoundError(str(folder_id))
    return folder


def list_for_owner(owner: User) -> list[Folder]:
    """All folders owned by `owner`, parent-first ordering."""
    return list(
        db.session.scalars(
            select(Folder)
            .where(Folder.owner_id == owner.id)
            .order_by(Folder.parent_id.nullsfirst(), Folder.name)
        )
    )


def create_folder(
    *, owner: User, name: str, parent_id: uuid.UUID | None = None
) -> Folder:
    """Create a new folder. Parent must belong to the same owner."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Folder name cannot be empty.")
    if len(name) > 256:
        raise ValueError("Folder name too long (max 256 chars).")

    if parent_id is not None:
        parent = db.session.get(Folder, parent_id)
        if parent is None or parent.owner_id != owner.id:
            raise InvalidParentError("Parent folder not found or not owned by you.")

    folder = Folder(owner_id=owner.id, parent_id=parent_id, name=name)
    db.session.add(folder)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise FolderConflictError(
            f"A folder named {name!r} already exists in that location."
        ) from None

    audit.record(
        "folder.created",
        actor=owner,
        target_type="folder",
        target_id=folder.id,
        metadata={"name": name, "parent_id": str(parent_id) if parent_id else None},
        commit=False,
    )
    db.session.commit()
    return folder


def delete_folder(folder: Folder, *, actor: User) -> None:
    """Delete an empty folder. Refuses if it has subfolders or files."""
    sub_count = (
        db.session.scalar(
            select(func.count()).select_from(Folder).where(Folder.parent_id == folder.id)
        )
        or 0
    )
    file_count = (
        db.session.scalar(
            select(func.count()).select_from(File).where(File.folder_id == folder.id)
        )
        or 0
    )
    if sub_count or file_count:
        raise FolderNotEmptyError(
            f"Folder is not empty ({sub_count} subfolders, {file_count} files)."
        )

    target_id = folder.id
    name = folder.name
    db.session.delete(folder)
    audit.record(
        "folder.deleted",
        actor=actor,
        target_type="folder",
        target_id=target_id,
        metadata={"name": name},
        commit=False,
    )
    db.session.commit()


# --- Tree helpers (used by shares + listing) ---


_DESCENDANTS_CTE = text(
    """
    WITH RECURSIVE tree(id) AS (
        SELECT id FROM folders WHERE id = ANY(:roots ::uuid[])
        UNION
        SELECT f.id FROM folders f JOIN tree t ON f.parent_id = t.id
    )
    SELECT id FROM tree
    """
)

_ANCESTORS_CTE = text(
    """
    WITH RECURSIVE up(id, parent_id) AS (
        SELECT id, parent_id FROM folders WHERE id = :start
        UNION
        SELECT f.id, f.parent_id
          FROM folders f JOIN up ON f.id = up.parent_id
    )
    SELECT id FROM up
    """
)


def descendant_folder_ids(root_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Return *root_ids* plus every folder transitively under any of them."""
    if not root_ids:
        return set()
    rows = db.session.execute(
        _DESCENDANTS_CTE, {"roots": [str(rid) for rid in root_ids]}
    )
    return {uuid.UUID(str(row[0])) for row in rows}


def ancestor_folder_ids(folder_id: uuid.UUID) -> list[uuid.UUID]:
    """Return the chain *folder_id, parent, grandparent, ...* up to the root.

    Used by the policy layer to walk up from a file's folder and check
    whether any ancestor has been shared with the user.
    """
    rows = db.session.execute(_ANCESTORS_CTE, {"start": str(folder_id)})
    return [uuid.UUID(str(row[0])) for row in rows]


def files_in_folders(folder_ids: set[uuid.UUID]) -> list[File]:
    """All files whose `folder_id` is in *folder_ids*. Used by share expansion."""
    if not folder_ids:
        return []
    return list(
        db.session.scalars(
            select(File).where(File.folder_id.in_(folder_ids))
        )
    )


def list_children(owner: User, parent_id: uuid.UUID | None) -> list[Folder]:
    """List immediate subfolders of `parent_id` (or root if None) for `owner`."""
    if parent_id is None:
        clause = and_(Folder.owner_id == owner.id, Folder.parent_id.is_(None))
    else:
        clause = and_(Folder.owner_id == owner.id, Folder.parent_id == parent_id)
    return list(db.session.scalars(select(Folder).where(clause).order_by(Folder.name)))
