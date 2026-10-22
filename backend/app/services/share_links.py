"""External share-link domain service.

Phase 8 — anyone with the link can download the referenced file until
revoked / expired / exhausted. The raw token is shown to the creator
exactly once at mint time; the DB only ever holds `SHA-256(token)`.

Why SHA-256, not Argon2: tokens are 256 random bits and brute force is
infeasible regardless of hash speed. The hash protects against the
"DB leak → instant link reuse" attack — same trick GitHub / Stripe use
for API tokens. Slow hashing would only buy a useless safety margin.

Tier policy: by default, files classified RESTRICTED cannot get external
links. Admins can override per-link via `force_for_restricted=True`.
This catches the obvious "marketing user emails the salary spreadsheet
to their personal address" misuse case without needing a separate
DLP layer.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.classification import ClassificationStatus, ClassificationTier
from app.models.file import File
from app.models.share_link import ShareLink
from app.models.user import User
from app.services import audit, classification, files

log = get_logger(__name__)


# --- Errors ---


class ShareLinkError(Exception):
    """Base class for share-link operation failures."""


class ShareLinkPermissionDeniedError(ShareLinkError):
    """Caller is not the granter or admin (used on revoke)."""


class ShareLinkTierBlockedError(ShareLinkError):
    """File is RESTRICTED and the caller is not allowed to override."""


class ShareLinkClassificationPendingError(ShareLinkError):
    """File hasn't been classified yet; we can't apply the tier policy."""


class ShareLinkNotFoundError(ShareLinkError):
    """Token doesn't match any row."""


class ShareLinkInvalidError(ShareLinkError):
    """Row exists but is revoked / expired / exhausted."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --- Dataclasses ---


@dataclass(frozen=True)
class MintedLink:
    """Returned by `create_link`. `token` is plaintext, shown ONCE."""

    link: ShareLink
    token: str


# --- Hashing ---


def _hash_token(token: str) -> str:
    """SHA-256 hex of *token*. Constant work, deterministic, no salt — the
    256-bit token is already its own salt."""
    return hashlib.sha256(token.encode("ascii"), usedforsecurity=True).hexdigest()


# --- Read helpers ---


def get_by_id(link_id: uuid.UUID) -> ShareLink | None:
    return db.session.get(ShareLink, link_id)


def list_granted(user: User) -> list[ShareLink]:
    """Active + historic links the user created. Sorted newest-first."""
    return list(
        db.session.scalars(
            select(ShareLink)
            .where(ShareLink.created_by_id == user.id)
            .order_by(ShareLink.created_at.desc())
        )
    )


def lookup_active(token: str) -> ShareLink:
    """Resolve *token* to a usable ShareLink. Raises ShareLinkNotFoundError
    if the hash matches nothing, ShareLinkInvalidError if it matches a
    row that is no longer usable. Callers MUST handle both errors.
    """
    if not token or len(token) < 16:
        raise ShareLinkNotFoundError("Token too short.")

    h = _hash_token(token)
    link = db.session.scalar(select(ShareLink).where(ShareLink.token_hash == h))
    if link is None:
        raise ShareLinkNotFoundError("No such link.")
    _validate_active(link)
    return link


def _validate_active(link: ShareLink) -> None:
    now = datetime.now(UTC)
    if link.revoked_at is not None:
        raise ShareLinkInvalidError("revoked")
    if link.expires_at is not None and link.expires_at <= now:
        raise ShareLinkInvalidError("expired")
    if link.max_uses is not None and link.use_count >= link.max_uses:
        raise ShareLinkInvalidError("exhausted")
    # Phase 9 — the file might have been trashed since the link was minted.
    # `link.file` re-loads via the relationship; if it's gone (hard-deleted)
    # the cascade would have removed the link too, so a NULL here means the
    # file row is still around but the user trashed it.
    if link.file is None or link.file.deleted_at is not None:
        raise ShareLinkInvalidError("file_removed")


# --- Mutations ---


def create_link(
    *,
    creator: User,
    file_id: uuid.UUID,
    expires_at: datetime | None = None,
    max_uses: int | None = None,
    force_for_restricted: bool = False,
) -> MintedLink:
    """Mint a fresh link for *file_id*. The caller MUST already own the file
    (or be admin). Returns both the persisted row and the plaintext token —
    the latter is shown to the user once and never persisted.
    """
    file_record = db.session.get(File, file_id)
    if file_record is None:
        raise ShareLinkError("File not found.")
    if file_record.owner_id != creator.id and not creator.is_admin:
        raise ShareLinkError("You can only mint links for files you own.")

    # Tier policy — block RESTRICTED unless admin opts in.
    current = classification.get_latest(file_id)
    if current is None or current.status != ClassificationStatus.COMPLETED:
        raise ShareLinkClassificationPendingError(
            "File hasn't finished classification yet."
        )
    if current.final_tier == ClassificationTier.RESTRICTED and not (
        creator.is_admin and force_for_restricted
    ):
        audit.record(
            "share_link.tier_blocked",
            actor=creator,
            target_type="file",
            target_id=file_id,
            metadata={
                "tier": current.final_tier.value,
                "filename": file_record.original_filename,
                "is_admin": creator.is_admin,
            },
            severity=AuditSeverity.WARNING,
        )
        raise ShareLinkTierBlockedError(
            "External links are not allowed for RESTRICTED files."
        )

    if max_uses is not None and max_uses < 1:
        raise ShareLinkError("max_uses must be 1 or more.")
    if expires_at is not None:
        # Strip microseconds to keep token URLs readable in audit data.
        expires_at = expires_at.replace(microsecond=0)
        if expires_at <= datetime.now(UTC):
            raise ShareLinkError("expires_at must be in the future.")

    token = secrets.token_urlsafe(32)  # 256 bits → 43-ish chars
    link = ShareLink(
        file_id=file_id,
        token_hash=_hash_token(token),
        created_by_id=creator.id,
        expires_at=expires_at,
        max_uses=max_uses,
    )
    db.session.add(link)
    db.session.flush()

    audit.record(
        "share_link.created",
        actor=creator,
        target_type="file",
        target_id=file_id,
        metadata={
            "share_link_id": str(link.id),
            "tier": current.final_tier.value,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "max_uses": max_uses,
            "tier_override": current.final_tier == ClassificationTier.RESTRICTED,
        },
        severity=(
            AuditSeverity.WARNING
            if current.final_tier == ClassificationTier.RESTRICTED
            else AuditSeverity.INFO
        ),
        commit=False,
    )
    db.session.commit()
    return MintedLink(link=link, token=token)


def revoke_link(link: ShareLink, *, actor: User) -> None:
    """Tombstone the link. Granter or admin only. Idempotent."""
    if not (actor.is_admin or actor.id == link.created_by_id):
        raise ShareLinkPermissionDeniedError(
            "Only the link creator or an admin can revoke this link."
        )
    if link.revoked_at is not None:
        return
    link.revoked_at = datetime.now(UTC)
    audit.record(
        "share_link.revoked",
        actor=actor,
        target_type="file",
        target_id=link.file_id,
        metadata={
            "share_link_id": str(link.id),
            "use_count": link.use_count,
            "max_uses": link.max_uses,
        },
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()


# --- Public download path ---


def record_viewed(link: ShareLink, *, requester_ip: str | None) -> None:
    """Audit event for landing-page hits. No-side-effects on the link row."""
    audit.record(
        "share_link.viewed",
        actor_ip=requester_ip,
        target_type="file",
        target_id=link.file_id,
        metadata={"share_link_id": str(link.id)},
        severity=AuditSeverity.INFO,
    )


def consume_and_stream(
    link: ShareLink, *, requester_ip: str | None
) -> tuple[File, Iterator[bytes]]:
    """Increment `use_count`, audit, and return (file_row, plaintext-iterator).

    Must be called inside a request context where the response immediately
    consumes the iterator. The use-count bump is committed BEFORE streaming
    so concurrent requests see the updated counter.
    """
    link.use_count += 1
    audit.record(
        "share_link.downloaded",
        actor_ip=requester_ip,
        target_type="file",
        target_id=link.file_id,
        metadata={
            "share_link_id": str(link.id),
            "use_count_after": link.use_count,
            "max_uses": link.max_uses,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()

    chunks = files.stream_download(link.file, actor=None, emit_audit=False)
    return link.file, chunks


def record_use_denied(reason: str, *, requester_ip: str | None) -> None:
    """Public-endpoint denial (404/410). Emitted for forensics — surfaces
    'someone tried an expired link from this IP' in audit reports.
    """
    audit.record(
        "share_link.use_denied",
        actor_ip=requester_ip,
        target_type="share_link",
        metadata={"reason": reason},
        severity=AuditSeverity.WARNING,
    )
