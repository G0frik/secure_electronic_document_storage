"""Files API blueprint."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from flask import Blueprint, Response, abort, jsonify, request
from pydantic import ValidationError
from werkzeug.utils import secure_filename

from app.models.file import File
from app.schemas.files import FileListParams
from app.services import classification, csrf, files, policy
from app.services.files import EmptyUploadError
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("files", __name__, url_prefix="/api/files")


def _file_payload(record: File) -> dict:
    return {
        "id": str(record.id),
        "owner_id": str(record.owner_id),
        "original_filename": record.original_filename,
        "mime_type": record.mime_type,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
    }


def _deny_response(decision: policy.Decision):  # type: ignore[no-untyped-def]
    payload = {
        "error": "access_denied",
        "reason": decision.reason,
        "tier": decision.tier.value if decision.tier else None,
        "message": _reason_message(decision.reason),
    }
    return jsonify(payload), 403


def _reason_message(reason: str) -> str:
    return {
        policy.REASON_POLICY_DENY_TIER: (
            "Your role is not permitted to access this document's classification tier."
        ),
        policy.REASON_POLICY_DENY_CATEGORY: (
            "Your role is not permitted to access this document's category."
        ),
        policy.REASON_POLICY_DENY_NOT_IN_ALLOWED: (
            "Your role's policy does not include this document's category."
        ),
        policy.REASON_NO_POLICY: (
            "No access policy applies to your role; default-deny."
        ),
        policy.REASON_NO_CLASSIFICATION: (
            "This document has not finished classification yet."
        ),
        policy.REASON_CLASSIFICATION_FAILED: (
            "This document's classification failed; access is denied until reclassified."
        ),
    }.get(reason, "Access denied.")


def _resolve_or_404(file_id: uuid.UUID) -> File:
    record = files.get_by_id(file_id)
    if record is None:
        abort(404, description="File not found.")
    return record


@bp.post("")
@login_required
@csrf.csrf_protect
def upload():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "invalid_request", "message": "Missing 'file' field."}), 400
    try:
        record = files.create_from_upload(owner=user, uploaded=uploaded)
    except EmptyUploadError as exc:
        return jsonify({"error": "empty_upload", "message": str(exc)}), 400
    return jsonify(_file_payload(record)), 201


@bp.get("")
@login_required
def list_files():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        params = FileListParams.model_validate(request.args.to_dict())
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    listing = files.list_for_owner(user, page=params.page, per_page=params.per_page)
    return jsonify(
        {
            "items": [_file_payload(f) for f in listing.items],
            "page": listing.page,
            "per_page": listing.per_page,
            "total": listing.total,
        }
    )


@bp.get("/<uuid:file_id>")
@login_required
def get_file(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    record = _resolve_or_404(file_id)
    decision = policy.can_user_access(user, record)
    if not decision.allowed:
        return _deny_response(decision)
    return jsonify(_file_payload(record))


@bp.get("/<uuid:file_id>/download")
@login_required
def download(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    record = _resolve_or_404(file_id)
    decision = policy.can_user_access(user, record)
    if not decision.allowed:
        return _deny_response(decision)

    chunks = files.stream_download(record, actor=user)

    # Filename header: ASCII fallback + RFC 5987 UTF-8 form for non-ASCII names.
    ascii_name = secure_filename(record.original_filename) or "download"
    quoted = quote(record.original_filename, safe="")
    headers = {
        "Content-Length": str(record.size_bytes),
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
        ),
    }
    return Response(chunks, mimetype=record.mime_type, headers=headers)


@bp.get("/<uuid:file_id>/classification")
@login_required
def get_classification(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Latest classification result for the file. Used by the SPA for polling.

    Owner sees their pending/running statuses (needed for the polling UI).
    Non-owners require the same RBAC check as `download` — if the policy
    would deny the file, the classification is not leaked either.
    """
    user = current_user_or_none()
    record = _resolve_or_404(file_id)

    # The owner can always see classification status on their own files
    # (otherwise pending uploads would 403 themselves). Non-owners go through
    # the policy as normal.
    if record.owner_id != user.id:
        decision = policy.can_user_access(user, record)
        if not decision.allowed:
            return _deny_response(decision)

    classification_row = classification.get_latest(record.id)
    if classification_row is None:
        return jsonify({"file_id": str(record.id), "status": "missing"}), 200
    return jsonify(classification.to_payload(classification_row)), 200
