"""Per-user storage quota (Phase 12).

`User.used_bytes` is denormalised — the upload + hard-delete paths
maintain it inline so the bell UI's quota bar is always cheap to render.
A nightly Celery task recomputes from `SUM(files.size_bytes)` as drift
protection.

Trashed files DO count toward quota — same model as Google Drive /
Dropbox. `used_bytes` only goes down on hard-delete (via the trash UI
or the 30-day reaper).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.extensions import db
from app.logging_config import get_logger
from app.models.file import File
from app.models.user import User

log = get_logger(__name__)


# --- Errors ---


class QuotaExceededError(Exception):
    """Raised by `check_quota_for_upload` when an upload would push the
    user's `used_bytes` past `quota_bytes`. The HTTP layer maps this to
    413 Payload Too Large.
    """

    def __init__(self, *, used: int, quota: int, requested: int) -> None:
        self.used = used
        self.quota = quota
        self.requested = requested
        self.available = max(0, quota - used)
        super().__init__(
            f"Upload of {requested} bytes would exceed quota "
            f"({used}/{quota} used, {self.available} available)."
        )


# --- Hooks called by file lifecycle ---


def check_quota_for_upload(owner: User, requested_bytes: int) -> None:
    """Raise `QuotaExceededError` if *owner* doesn't have headroom for
    *requested_bytes*. Cheap — reads in-memory User attrs only.
    """
    if requested_bytes <= 0:
        return  # empty uploads are caught earlier
    if owner.used_bytes + requested_bytes > owner.quota_bytes:
        raise QuotaExceededError(
            used=owner.used_bytes,
            quota=owner.quota_bytes,
            requested=requested_bytes,
        )


def increment_used(owner: User, bytes_added: int) -> None:
    """Bump `used_bytes` on the same SQLAlchemy session as the file insert.

    Caller is responsible for committing. We don't commit here so the
    counter and the file row land atomically.
    """
    if bytes_added <= 0:
        return
    owner.used_bytes = owner.used_bytes + bytes_added


def decrement_used(owner: User | None, bytes_removed: int) -> None:
    """Reverse of `increment_used`. Clamps at 0 to avoid negative counters
    if drift ever pushed `used_bytes` below the truth.
    """
    if owner is None or bytes_removed <= 0:
        return
    owner.used_bytes = max(0, owner.used_bytes - bytes_removed)


# --- Drift safety ---


def recompute_for(user: User) -> int:
    """Set *user*.used_bytes to the live SUM over `files`. Returns the new
    value. Caller must commit.
    """
    total = (
        db.session.scalar(
            select(func.coalesce(func.sum(File.size_bytes), 0)).where(
                File.owner_id == user.id
            )
        )
        or 0
    )
    user.used_bytes = int(total)
    return int(total)


def recompute_all() -> int:
    """Recompute `used_bytes` for every active user. Returns the count of
    users touched. Single DB transaction.
    """
    users = list(db.session.scalars(select(User)))
    for user in users:
        recompute_for(user)
    db.session.commit()
    log.info("quota.recompute_all", user_count=len(users))
    return len(users)
