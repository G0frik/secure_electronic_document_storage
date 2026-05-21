"""Files API blueprint."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from flask import Blueprint, Response, abort, jsonify, request
from pydantic import ValidationError
from werkzeug.utils import secure_filename

from app.models.file import File
from app.schemas.files import FileListParams
from app.services import (
    classification,
    csrf,
    file_versions,
    files,
    folders,
    policy,
    preview,
    trash,
)
from app.services.file_versions import (
    VersionNotFoundError,
    VersionUploadError,
)
from app.services.files import EmptyUploadError, FileNotFoundError
from app.services.folders import FolderNotFoundError
from app.services.preview import PreviewExtractionError, UnsupportedPreviewError
from app.services.quota import QuotaExceededError
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("files", __name__, url_prefix="/api/files")


def _file_payload(record: File) -> dict:
    return {
        "id": str(record.id),
        "owner_id": str(record.owner_id),
        "folder_id": str(record.folder_id) if record.folder_id else None,
        "original_filename": record.original_filename,
        "mime_type": record.mime_type,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
        "current_version": record.current_version,
    }


def _version_payload(view) -> dict:  # type: ignore[no-untyped-def]
    return {
        "version_number": view.version_number,
        "is_current": view.is_current,
        "original_filename": view.original_filename,
        "mime_type": view.mime_type,
        "size_bytes": view.size_bytes,
        "sha256": view.sha256,
        "kek_version": view.kek_version,
        "uploader_id": str(view.uploader_id) if view.uploader_id else None,
        "uploaded_at": view.uploaded_at.isoformat() if view.uploaded_at else None,
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

    # Phase 7: optional folder placement. The form field is `folder_id`.
    folder_id_str = request.form.get("folder_id") or None
    folder_uuid: uuid.UUID | None = None
    if folder_id_str:
        try:
            folder_uuid = uuid.UUID(folder_id_str)
        except ValueError:
            return jsonify({"error": "invalid_request", "message": "Bad folder_id."}), 400
        try:
            folders.get_for_owner(folder_uuid, user)
        except FolderNotFoundError:
            return jsonify({"error": "invalid_request", "message": "Folder not found."}), 400

    try:
        record = files.create_from_upload(owner=user, uploaded=uploaded, folder_id=folder_uuid)
    except EmptyUploadError as exc:
        return jsonify({"error": "empty_upload", "message": str(exc)}), 400
    except QuotaExceededError as exc:
        return (
            jsonify(
                {
                    "error": "quota_exceeded",
                    "message": str(exc),
                    "used_bytes": exc.used,
                    "quota_bytes": exc.quota,
                    "requested_bytes": exc.requested,
                    "available_bytes": exc.available,
                }
            ),
            413,
        )
    return jsonify(_file_payload(record)), 201


@bp.get("")
@login_required
def list_files():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        params = FileListParams.model_validate(request.args.to_dict())
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    listing = files.list_for_owner(
        user,
        page=params.page,
        per_page=params.per_page,
        folder_id=params.folder_id,
        folder_scope=params.folder_scope,
    )
    return jsonify(
        {
            "items": [_file_payload(f) for f in listing.items],
            "page": listing.page,
            "per_page": listing.per_page,
            "total": listing.total,
        }
    )


@bp.get("/shared")
@login_required
def list_shared():  # type: ignore[no-untyped-def]
    """Phase 7 — files the user reaches via active shares (direct or folder).
    Already filtered through Phase 5 policy, so denied-category files don't
    appear even when shared.
    """
    user = current_user_or_none()
    items = files.list_shared_with(user)
    return jsonify({"items": [_file_payload(f) for f in items], "total": len(items)})


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


@bp.delete("/<uuid:file_id>")
@login_required
@csrf.csrf_protect
def soft_delete(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Phase 9 — move the file to the user's trash. Owner-only (admins use
    the same path on their own files; cross-owner deletion isn't supported
    here even for admins — that would be an explicit admin action in Phase 14).
    """
    user = current_user_or_none()
    try:
        record = files.get_for_owner(file_id, user)
    except FileNotFoundError:
        abort(404, description="File not found.")
    trash.soft_delete(record, actor=user)
    return ("", 204)


@bp.get("/<uuid:file_id>/preview")
@login_required
def preview_file(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Phase 14 — return a textual preview of the file (first ~100 KB).

    Supports text formats + PDF + DOCX. Anything else returns 415.
    Same policy check as download — non-owner non-admin must pass tier
    rules. The owner short-circuits as usual.
    """
    user = current_user_or_none()
    record = _resolve_or_404(file_id)

    if record.owner_id != user.id:
        decision = policy.can_user_access(user, record)
        if not decision.allowed:
            return _deny_response(decision)

    try:
        payload = preview.build_preview(record, actor=user)
    except UnsupportedPreviewError as exc:
        return (
            jsonify(
                {
                    "error": "unsupported_preview",
                    "message": (
                        "Preview is not available for this file type. "
                        "Download the file to view it."
                    ),
                    "detail": str(exc),
                }
            ),
            415,
        )
    except PreviewExtractionError as exc:
        return (
            jsonify(
                {
                    "error": "preview_failed",
                    "message": (
                        "We couldn't extract text from this file (it may be "
                        "corrupt, password-protected, or scanned)."
                    ),
                    "detail": str(exc),
                }
            ),
            422,
        )

    return jsonify(
        {
            "file_id": str(record.id),
            "filename": record.original_filename,
            "mime_type": record.mime_type,
            "size_bytes": record.size_bytes,
            "extractor": payload.extractor,
            "truncated": payload.truncated,
            "preview_bytes": len(payload.text.encode("utf-8", errors="replace")),
            "original_bytes": payload.original_bytes,
            "text": payload.text,
        }
    )


@bp.post("/<uuid:file_id>/versions")
@login_required
@csrf.csrf_protect
def upload_new_version(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Phase 15 — owner uploads a new version of an existing file.

    Snapshots the current content into `file_versions`, then overwrites
    the file row with the new content and bumps `current_version`. Triggers
    re-classification on the new content.
    """
    user = current_user_or_none()
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "invalid_request", "message": "Missing 'file' field."}), 400

    # Owner-only. Admins managing another user's file should use the admin
    # reclassify path, not this one — versions belong to the owner's quota.
    try:
        record = files.get_for_owner(file_id, user)
    except FileNotFoundError:
        abort(404, description="File not found.")

    try:
        updated = file_versions.upload_new_version(
            file_record=record, uploaded=uploaded, uploader=user
        )
    except VersionUploadError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    except QuotaExceededError as exc:
        return (
            jsonify(
                {
                    "error": "quota_exceeded",
                    "message": str(exc),
                    "used_bytes": exc.used,
                    "quota_bytes": exc.quota,
                    "requested_bytes": exc.requested,
                    "available_bytes": exc.available,
                }
            ),
            413,
        )
    return jsonify(_file_payload(updated)), 201


@bp.get("/<uuid:file_id>/versions")
@login_required
def list_versions(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """List every version of the file (current + history), newest-first.

    Owner-only — sharing semantics don't currently extend to old versions.
    Admins can call this too via the admin bypass.
    """
    user = current_user_or_none()
    record = _resolve_or_404(file_id)
    if record.owner_id != user.id and user.role.value != "admin":
        return jsonify({"error": "access_denied", "reason": "not_owner"}), 403

    views = file_versions.list_versions(record)
    return jsonify({"items": [_version_payload(v) for v in views]})


@bp.get("/<uuid:file_id>/versions/<int:version_number>/download")
@login_required
def download_version(  # type: ignore[no-untyped-def]
    file_id: uuid.UUID, version_number: int
):
    """Download a specific version of the file. Reuses the same RBAC path
    as the regular download endpoint for the *current* version; historical
    versions are owner/admin-only.
    """
    user = current_user_or_none()
    record = _resolve_or_404(file_id)

    try:
        is_current, version_row = file_versions.get_version(record, version_number)
    except VersionNotFoundError:
        abort(404, description="Version not found.")

    if is_current:
        # Phase 5 RBAC for the current version (non-owners need policy
        # access). Historical versions are owner/admin-only — no sharing
        # semantics today.
        decision = policy.can_user_access(user, record)
        if not decision.allowed:
            return _deny_response(decision)
        chunks = files.stream_download(record, actor=user)
        original_filename = record.original_filename
        mime_type = record.mime_type
        size = record.size_bytes
    else:
        if record.owner_id != user.id and user.role.value != "admin":
            return jsonify({"error": "access_denied", "reason": "not_owner"}), 403
        assert version_row is not None  # narrow for mypy
        chunks = file_versions.stream_version_download(
            record, version_row, actor=user
        )
        original_filename = version_row.original_filename
        mime_type = version_row.mime_type
        size = version_row.size_bytes

    ascii_name = secure_filename(original_filename) or "download"
    quoted = quote(original_filename, safe="")
    headers = {
        "Content-Length": str(size),
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
        ),
    }
    return Response(chunks, mimetype=mime_type, headers=headers)


@bp.delete("/<uuid:file_id>/versions/<int:version_number>")
@login_required
@csrf.csrf_protect
def delete_version(  # type: ignore[no-untyped-def]
    file_id: uuid.UUID, version_number: int
):
    """Delete a single historical version. Refuses to delete the current
    version — callers should soft-delete the whole file via DELETE /api/files
    instead.
    """
    user = current_user_or_none()
    try:
        record = files.get_for_owner(file_id, user)
    except FileNotFoundError:
        abort(404, description="File not found.")

    try:
        is_current, version_row = file_versions.get_version(record, version_number)
    except VersionNotFoundError:
        abort(404, description="Version not found.")

    if is_current:
        return (
            jsonify(
                {
                    "error": "invalid_request",
                    "message": "Cannot delete the current version — delete the file instead.",
                }
            ),
            409,
        )
    assert version_row is not None
    file_versions.delete_version(record, version_row, actor=user)
    return ("", 204)


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
