"""Tier-override workflow service (Phase 10).

Human-in-the-loop on the auto-classifier: a file owner can dispute the
tier their document landed at, attach a justification, and an admin
either approves or denies the change.

Approval semantics: instead of mutating the original classification row
(which would lose audit), we INSERT a new Classification with the next
version number, marked `classifier_version='manual:override'`. The
policy layer's `get_latest` orders by `version DESC`, so the override
becomes the effective tier automatically — no rewiring of consumers.

Constraint: a single file can have at most one pending request at a
time (partial unique index on the migration). If the user wants to
change a previously approved/denied outcome, they file a fresh request.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.file import File
from app.models.tier_override import OverrideStatus, TierOverrideRequest
from app.models.user import User
from app.services import audit, classification

log = get_logger(__name__)

_MANUAL_CLASSIFIER_VERSION = "manual:override"
_MAX_JUSTIFICATION_CHARS = 2_000


class TierOverrideError(Exception):
    """Base class for override workflow failures."""


class PendingRequestExistsError(TierOverrideError):
    """A pending request already exists for this file."""


class NotPendingError(TierOverrideError):
    """Tried to approve/deny a request that's already been decided."""


class NoClassificationError(TierOverrideError):
    """File has no completed classification to override."""


class SameTierError(TierOverrideError):
    """Requested tier equals current tier — nothing to do."""


# --- Read helpers ---


def get_by_id(request_id: uuid.UUID) -> TierOverrideRequest | None:
    return db.session.get(TierOverrideRequest, request_id)


def list_for_file(file_id: uuid.UUID) -> list[TierOverrideRequest]:
    return list(
        db.session.scalars(
            select(TierOverrideRequest)
            .where(TierOverrideRequest.file_id == file_id)
            .order_by(TierOverrideRequest.created_at.desc())
        )
    )


def list_pending() -> list[TierOverrideRequest]:
    return list(
        db.session.scalars(
            select(TierOverrideRequest)
            .where(TierOverrideRequest.status == OverrideStatus.PENDING)
            .order_by(TierOverrideRequest.created_at)
        )
    )


# --- Mutations ---


def create_request(
    *,
    file: File,
    requested_tier: ClassificationTier,
    justification: str,
    actor: User,
) -> TierOverrideRequest:
    """Owner files a tier-override request. The current classification is
    snapshotted so a later auto-reclassification doesn't change the
    "from" tier of an in-flight request.
    """
    justification = (justification or "").strip()
    if not justification:
        raise TierOverrideError("Justification is required.")
    if len(justification) > _MAX_JUSTIFICATION_CHARS:
        raise TierOverrideError(
            f"Justification too long (max {_MAX_JUSTIFICATION_CHARS} chars)."
        )

    current = classification.get_latest(file.id)
    if current is None or current.status != ClassificationStatus.COMPLETED:
        raise NoClassificationError(
            "File has no completed classification to override yet."
        )

    if current.final_tier == requested_tier:
        raise SameTierError(
            f"File is already classified as {requested_tier.value}."
        )

    request = TierOverrideRequest(
        file_id=file.id,
        classification_id=current.id,
        requested_by_id=actor.id,
        current_tier=current.final_tier,
        requested_tier=requested_tier,
        justification=justification,
        status=OverrideStatus.PENDING,
    )
    db.session.add(request)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise PendingRequestExistsError(
            "This file already has a pending tier-override request."
        ) from None

    audit.record(
        "tier_override.requested",
        actor=actor,
        target_type="file",
        target_id=file.id,
        metadata={
            "request_id": str(request.id),
            "current_tier": current.final_tier.value,
            "requested_tier": requested_tier.value,
            "classification_id": str(current.id),
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return request


def approve(
    request: TierOverrideRequest,
    *,
    reviewer: User,
    decision_reason: str | None = None,
) -> Classification:
    """Admin approves: write the override Classification row, mark the
    request approved, audit. Returns the newly-inserted Classification
    so the caller can show the user the updated tier in one round-trip.
    """
    if request.status != OverrideStatus.PENDING:
        raise NotPendingError(
            f"Request is already {request.status.value}."
        )

    next_version = (
        db.session.scalar(
            select(func.coalesce(func.max(Classification.version), 0)).where(
                Classification.file_id == request.file_id
            )
        )
        or 0
    ) + 1

    new_classification = Classification(
        file_id=request.file_id,
        version=next_version,
        status=ClassificationStatus.COMPLETED,
        final_tier=request.requested_tier,
        # zero_shot/presidio left NULL — this row records a human decision,
        # not a model output.
        classifier_version=_MANUAL_CLASSIFIER_VERSION,
        classified_at=datetime.now(timezone.utc),
    )
    db.session.add(new_classification)

    request.status = OverrideStatus.APPROVED
    request.reviewed_by_id = reviewer.id
    request.reviewed_at = datetime.now(timezone.utc)
    request.decision_reason = (decision_reason or "").strip() or None

    audit.record(
        "tier_override.approved",
        actor=reviewer,
        target_type="file",
        target_id=request.file_id,
        metadata={
            "request_id": str(request.id),
            "current_tier": request.current_tier.value,
            "requested_tier": request.requested_tier.value,
            "new_classification_version": next_version,
            "decision_reason": request.decision_reason,
        },
        severity=AuditSeverity.WARNING,
        commit=False,
    )
    db.session.commit()
    return new_classification


def deny(
    request: TierOverrideRequest,
    *,
    reviewer: User,
    decision_reason: str | None = None,
) -> TierOverrideRequest:
    """Admin denies. No classification change."""
    if request.status != OverrideStatus.PENDING:
        raise NotPendingError(
            f"Request is already {request.status.value}."
        )

    request.status = OverrideStatus.DENIED
    request.reviewed_by_id = reviewer.id
    request.reviewed_at = datetime.now(timezone.utc)
    request.decision_reason = (decision_reason or "").strip() or None

    audit.record(
        "tier_override.denied",
        actor=reviewer,
        target_type="file",
        target_id=request.file_id,
        metadata={
            "request_id": str(request.id),
            "current_tier": request.current_tier.value,
            "requested_tier": request.requested_tier.value,
            "decision_reason": request.decision_reason,
        },
        severity=AuditSeverity.INFO,
        commit=False,
    )
    db.session.commit()
    return request
