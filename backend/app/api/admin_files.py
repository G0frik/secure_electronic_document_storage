"""Admin file operations (Phase 13). Currently: reclassify on demand."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify

from app.models.audit import AuditSeverity
from app.services import audit, classification, csrf, files
from app.utils.auth_decorators import admin_required, current_user_or_none

bp = Blueprint("admin_files", __name__, url_prefix="/api/admin/files")


@bp.post("/<uuid:file_id>/reclassify")
@admin_required
@csrf.csrf_protect
def reclassify(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Insert a fresh PENDING Classification row at `version = MAX+1` and
    enqueue the worker. The latest-Classification consumers (policy, share-
    link landing, file payload) automatically pick up the new tier once the
    worker finishes.

    Returns 202 Accepted + the new classification row payload so the SPA
    can start polling `/api/files/<id>/classification` for the result.
    """
    actor = current_user_or_none()
    # Include trashed so admin can reclassify before purging.
    record = files.get_by_id(file_id, include_trashed=True)
    if record is None:
        abort(404, description="File not found.")

    new_row = classification.request_reclassification(record.id)

    audit.record(
        "admin.file.reclassify_requested",
        actor=actor,
        target_type="file",
        target_id=record.id,
        metadata={
            "filename": record.original_filename,
            "new_classification_version": new_row.version,
        },
        severity=AuditSeverity.INFO,
    )

    # Lazy import — keep Celery off the API hot path.
    from app.tasks.classification import classify_file

    classify_file.delay(str(record.id))

    return (
        jsonify(
            {
                "file_id": str(record.id),
                "classification_version": new_row.version,
                "status": new_row.status.value,
            }
        ),
        202,
    )
