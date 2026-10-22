"""Tag domain service (Phase 10).

Free-text labels users attach to their own files. Names are normalised
on the way in (trim + lowercase, allow internal whitespace collapsed to
single spaces) and the `tags.name` UNIQUE constraint makes that the dedup
boundary. Adding a tag is idempotent — re-adding the same name to the
same file is a no-op (the FileTag PK blocks the duplicate).
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.logging_config import get_logger
from app.models.tag import FileTag, Tag
from app.models.user import User
from app.services import audit

log = get_logger(__name__)

_WHITESPACE = re.compile(r"\s+")
_MAX_NAME = 64
_MAX_TAGS_PER_FILE = 32


class TagError(Exception):
    """Base class for tag failures."""


class InvalidTagNameError(TagError):
    """Name was empty after normalisation or exceeded the max length."""


class TooManyTagsError(TagError):
    """File already at the per-file tag cap."""


def normalise_name(raw: str) -> str:
    """Lower / trim / collapse internal whitespace. Empty input raises."""
    if raw is None:
        raise InvalidTagNameError("Tag name is required.")
    cleaned = _WHITESPACE.sub(" ", raw.strip().lower())
    if not cleaned:
        raise InvalidTagNameError("Tag name cannot be empty.")
    if len(cleaned) > _MAX_NAME:
        raise InvalidTagNameError(
            f"Tag name too long (max {_MAX_NAME} chars)."
        )
    return cleaned


def get_or_create(name: str) -> Tag:
    """Return the Tag row for *name*, creating it if missing. The function
    is racy in the abstract — two parallel callers could both INSERT — so
    the UNIQUE on `name` catches the loser and we re-fetch.
    """
    normalised = normalise_name(name)
    existing = db.session.scalar(select(Tag).where(Tag.name == normalised))
    if existing is not None:
        return existing

    tag = Tag(name=normalised)
    db.session.add(tag)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        existing = db.session.scalar(select(Tag).where(Tag.name == normalised))
        # The UNIQUE only fires when somebody else inserted the same name.
        if existing is None:
            raise
        return existing
    return tag


def list_for_file(file_id: uuid.UUID) -> list[Tag]:
    """Tags currently on *file_id*, ordered by name."""
    return list(
        db.session.scalars(
            select(Tag)
            .join(FileTag, FileTag.tag_id == Tag.id)
            .where(FileTag.file_id == file_id)
            .order_by(Tag.name)
        )
    )


def add_to_file(
    *, file_id: uuid.UUID, names: list[str], actor: User
) -> list[Tag]:
    """Apply each *names* entry to *file_id*. Idempotent on duplicates;
    refuses to push past the per-file cap.

    Returns the resulting set of tags on the file (sorted), so callers can
    skip a follow-up GET.
    """
    if not names:
        return list_for_file(file_id)

    current_count = (
        db.session.scalar(
            select(db.func.count())
            .select_from(FileTag)
            .where(FileTag.file_id == file_id)
        )
        or 0
    )

    # De-dupe + normalise the incoming list before doing any DB writes so
    # the cap math is precise.
    normalised: list[str] = []
    for raw in names:
        n = normalise_name(raw)
        if n not in normalised:
            normalised.append(n)

    # Figure out which of these aren't already on the file.
    existing_names = {t.name for t in list_for_file(file_id)}
    to_add = [n for n in normalised if n not in existing_names]
    if current_count + len(to_add) > _MAX_TAGS_PER_FILE:
        raise TooManyTagsError(
            f"A file may have at most {_MAX_TAGS_PER_FILE} tags."
        )

    for name in to_add:
        tag = get_or_create(name)
        link = FileTag(
            file_id=file_id, tag_id=tag.id, applied_by_id=actor.id
        )
        db.session.add(link)
        try:
            db.session.flush()
        except IntegrityError:
            # PK race — same (file_id, tag_id) inserted by another request.
            db.session.rollback()
            continue
        audit.record(
            "tag.added",
            actor=actor,
            target_type="file",
            target_id=file_id,
            metadata={"tag_id": str(tag.id), "name": tag.name},
            commit=False,
        )
    db.session.commit()
    return list_for_file(file_id)


def remove_from_file(
    *, file_id: uuid.UUID, tag_id: uuid.UUID, actor: User
) -> None:
    """Detach a tag from a file. No-op if it wasn't applied."""
    link = db.session.scalar(
        select(FileTag).where(
            FileTag.file_id == file_id, FileTag.tag_id == tag_id
        )
    )
    if link is None:
        return
    name = link.tag.name if link.tag else None
    db.session.delete(link)
    audit.record(
        "tag.removed",
        actor=actor,
        target_type="file",
        target_id=file_id,
        metadata={"tag_id": str(tag_id), "name": name},
        commit=False,
    )
    db.session.commit()
