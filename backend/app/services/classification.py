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

import os
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.classification import Classification, ClassificationStatus, ClassificationTier
from app.models.file import File
from app.services import audit, crypto, storage

log = get_logger(__name__)


def create_pending(file_id: uuid.UUID, *, commit: bool = True) -> Classification:
    """Insert a new PENDING Classification row for *file_id*. Idempotent on retry."""
    existing = db.session.scalar(
        select(Classification).where(Classification.file_id == file_id, Classification.version == 1)
    )
    if existing is not None:
        return existing
    record = Classification(
        file_id=file_id,
        version=1,
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
    from sqlalchemy import func as sa_func

    next_version = (
        db.session.scalar(
            select(sa_func.coalesce(sa_func.max(Classification.version), 0)).where(
                Classification.file_id == file_id
            )
        )
        or 0
    ) + 1
    record = Classification(
        file_id=file_id,
        version=next_version,
        status=ClassificationStatus.PENDING,
    )
    db.session.add(record)
    db.session.commit()
    return record


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
    """Worker entrypoint. Idempotent by (file_id, version=1).

    Steps: load file row → fetch ciphertext → decrypt → write temp file →
    extract text → classify → update Classification row → audit → cleanup.

    On any failure the row is marked FAILED with the error message captured
    and an audit event written. Exceptions are NOT re-raised — Celery would
    otherwise retry and we don't want infinite retry loops for bad files.
    """
    # Lazy import — keeps `transformers` out of the web process unless used.
    from app.classifier_core import CLASSIFIER_VERSION, ClassifyResult, classify, get_text
    from app.classifier_core.extract import UnsupportedExtensionError

    file_record = db.session.get(File, file_id)
    if file_record is None:
        log.warning("classify.file_missing", file_id=str(file_id))
        raise LookupError(f"File {file_id} not found.")

    record = create_pending(file_id, commit=False)
    record.status = ClassificationStatus.RUNNING
    db.session.commit()

    fn = classifier_fn or classify
    temp_path: Path | None = None
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

        # 2. Write to a named temp file so format-specific extractors can open it by path.
        suffix = Path(file_record.original_filename).suffix or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as buf:
            buf.write(plaintext)
            temp_path = Path(buf.name)

        # 3. Extract text + classify.
        text = get_text(temp_path)
        if not text.strip():
            raise ValueError("No text extracted (file may be empty or scanned PDF without OCR).")

        result = fn(text)
        if not isinstance(result, ClassifyResult):
            raise TypeError(f"classifier returned {type(result).__name__}, expected ClassifyResult")

        # 4. Persist result.
        record.final_tier = ClassificationTier(result.final_tier.value)
        record.zero_shot_tier = ClassificationTier(result.zero_shot_tier.value)
        record.presidio_tier = ClassificationTier(result.presidio_tier.value)
        record.raw_scores = result.raw_scores
        record.categories_triggered = result.categories_triggered
        record.presidio_entities = result.presidio_entities
        record.classifier_version = CLASSIFIER_VERSION
        record.status = ClassificationStatus.COMPLETED
        record.classified_at = datetime.now(timezone.utc)
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
            },
            severity=AuditSeverity.INFO,
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
        record.classified_at = datetime.now(timezone.utc)
        db.session.commit()
        audit.record(
            "classification.failed",
            target_type="file",
            target_id=file_record.id,
            metadata={"error": str(exc)[:500]},
            severity=AuditSeverity.WARNING,
        )
        return record

    finally:
        if temp_path is not None and temp_path.exists():
            try:
                os.unlink(temp_path)
            except OSError as exc:
                log.warning("classify.tempfile_cleanup_failed", path=str(temp_path), error=str(exc))


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
        "error_message": record.error_message,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "classified_at": record.classified_at.isoformat() if record.classified_at else None,
    }
