"""Classification service — DB ops + worker entrypoint.

The actual ML pipeline lives in `app/classifier_core/`. This module:
  - Creates the initial PENDING row at upload time
  - Updates the row (RUNNING → COMPLETED / FAILED) from the Celery task
  - Provides the read helper used by `GET /api/files/<id>/classification`

`run_classification(file_id)` is the worker entrypoint. It accepts an
optional `classifier_fn` so tests can mock the heavy model without
loading transformers.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.classification import Classification, ClassificationStatus, ClassificationTier
from app.models.file import File
from app.services import audit, crypto, storage

log = get_logger(__name__)


def create_pending(file_id: uuid.UUID, *, commit: bool = True) -> Classification:
    """Insert a PENDING row for the file's current content (one per uploaded
    version). Reuses the latest row while it is still PENDING: the worker
    hasn't read the content yet, so it will classify whatever is current.
    """
    latest = get_latest(file_id)
    if latest is not None and latest.status == ClassificationStatus.PENDING:
        return latest
    record = Classification(
        file_id=file_id,
        version=_next_version(file_id),
        status=ClassificationStatus.PENDING,
    )
    db.session.add(record)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return record


def request_reclassification(file_id: uuid.UUID) -> Classification:
    """Phase 13 admin reclassify. Inserts a new PENDING row at
    `version = MAX(existing.version) + 1` so the worker re-classifies the
    same file without losing the historical decisions. Callers enqueue
    `classify_file.delay(file_id)` after committing.
    """
    record = Classification(
        file_id=file_id,
        version=_next_version(file_id),
        status=ClassificationStatus.PENDING,
    )
    db.session.add(record)
    db.session.commit()
    return record


def _next_version(file_id: uuid.UUID) -> int:
    return (
        db.session.scalar(
            select(func.coalesce(func.max(Classification.version), 0)).where(
                Classification.file_id == file_id
            )
        )
        or 0
    ) + 1


def get_latest(file_id: uuid.UUID) -> Classification | None:
    """Return the latest (highest-version) classification row for *file_id*."""
    return db.session.scalar(
        select(Classification)
        .where(Classification.file_id == file_id)
        .order_by(Classification.version.desc())
    )


def run_classification(
    file_id: uuid.UUID,
    *,
    classifier_fn: Callable[[str], object] | None = None,
) -> Classification:
    """Worker entrypoint. Classifies into the file's latest row while it is
    PENDING/RUNNING; a decided latest row (e.g. a duplicate task, or an
    approved manual override) is returned untouched.

    Steps: load file row → fetch ciphertext → decrypt → extract text in
    memory (plaintext never touches the disk) → classify → update
    Classification row → audit.

    On any failure the row is marked FAILED with the error message captured
    and an audit event written. Exceptions are NOT re-raised — Celery would
    otherwise retry and we don't want infinite retry loops for bad files.
    """
    # Lazy import — keeps `transformers` out of the web process unless used.
    from app.classifier_core import CLASSIFIER_VERSION
    from app.classifier_core.extract import UnsupportedExtensionError, get_views_bytes
    from app.classifier_core.pipeline import classify_views

    file_record = db.session.get(File, file_id)
    if file_record is None:
        log.warning("classify.file_missing", file_id=str(file_id))
        raise LookupError(f"File {file_id} not found.")

    record = get_latest(file_id)
    if record is None:
        record = create_pending(file_id, commit=False)
    elif record.status not in (ClassificationStatus.PENDING, ClassificationStatus.RUNNING):
        log.info("classify.nothing_pending", file_id=str(file_id), version=record.version)
        return record
    record.status = ClassificationStatus.RUNNING
    db.session.commit()

    try:
        # 1. Pull ciphertext from MinIO and decrypt.
        response = storage.get(str(file_record.storage_key))
        try:
            ciphertext = b"".join(response.stream(64 * 1024))
        finally:
            response.close()
            response.release_conn()

        plaintext = crypto.decrypt_file(
            ciphertext=ciphertext,
            wrapped_dek=file_record.wrapped_dek,
            nonce=file_record.nonce,
            auth_tag=file_record.auth_tag,
            kek_version=file_record.kek_version,
        )

        # 2. Extract text in memory + classify with the configured engine and defenses.
        views = get_views_bytes(plaintext, file_record.original_filename)
        if not views.full.strip():
            raise ValueError("No text extracted (file may be empty or scanned PDF without OCR).")

        result = classify_views(views, classifier_fn)

        # 3. Persist result.
        record.final_tier = ClassificationTier(result.final_tier.value)
        record.zero_shot_tier = ClassificationTier(result.zero_shot_tier.value)
        record.presidio_tier = ClassificationTier(result.presidio_tier.value)
        record.raw_scores = result.raw_scores
        record.categories_triggered = result.categories_triggered
        record.presidio_entities = result.presidio_entities
        record.classifier_version = CLASSIFIER_VERSION
        record.classifier_config = result.config
        record.status = ClassificationStatus.COMPLETED
        record.classified_at = datetime.now(UTC)
        db.session.commit()

        audit.record(
            "classification.completed",
            target_type="file",
            target_id=file_record.id,
            metadata={
                "final_tier": record.final_tier.value,
                "zero_shot_tier": record.zero_shot_tier.value,
                "presidio_tier": record.presidio_tier.value,
                "categories_triggered": result.categories_triggered,
                "classifier_version": CLASSIFIER_VERSION,
                "classifier_config": result.config,
            },
            severity=AuditSeverity.INFO,
        )
        if result.needs_review:
            audit.record(
                "classification.needs_review",
                target_type="file",
                target_id=file_record.id,
                metadata={"reason": "injection detector flagged the document"} | result.config,
                severity=AuditSeverity.WARNING,
            )
        log.info(
            "classify.completed",
            file_id=str(file_id),
            final_tier=record.final_tier.value,
            zero_shot_tier=record.zero_shot_tier.value,
            presidio_tier=record.presidio_tier.value,
        )
        return record

    except (UnsupportedExtensionError, ValueError, TypeError, Exception) as exc:
        log.exception("classify.failed", file_id=str(file_id), error=str(exc))
        record.status = ClassificationStatus.FAILED
        record.error_message = str(exc)[:500]
        record.classified_at = datetime.now(UTC)
        db.session.commit()
        audit.record(
            "classification.failed",
            target_type="file",
            target_id=file_record.id,
            metadata={"error": str(exc)[:500]},
            severity=AuditSeverity.WARNING,
        )
        return record


def to_payload(record: Classification) -> dict:
    """API-ready dict shape for /api/files/<id>/classification."""
    return {
        "file_id": str(record.file_id),
        "version": record.version,
        "status": record.status.value,
        "final_tier": record.final_tier.value if record.final_tier else None,
        "zero_shot_tier": record.zero_shot_tier.value if record.zero_shot_tier else None,
        "presidio_tier": record.presidio_tier.value if record.presidio_tier else None,
        "categories_triggered": record.categories_triggered,
        "raw_scores": record.raw_scores,
        "presidio_entities": record.presidio_entities,
        "classifier_version": record.classifier_version,
        "classifier_config": record.classifier_config,
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "classified_at": record.classified_at.isoformat() if record.classified_at else None,
    }
