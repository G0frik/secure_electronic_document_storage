"""Trash API blueprint (Phase 9).

  GET    /api/trash             — list of the caller's soft-deleted files
  POST   /api/trash/<id>/restore — bring the file back to life
  DELETE /api/trash/<id>        — hard-delete now (skip the 30-day wait)

The DELETE on /api/files/<id> (soft-delete entry point) lives in
api/files.py.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify

from app.models.file import File
from app.services import csrf, files, trash
from app.services.files import FileNotFoundError
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("trash", __name__, url_prefix="/api/trash")


def _trash_payload(record: File) -> dict:
    return {
        "id": str(record.id),
        "owner_id": str(record.owner_id),
        "folder_id": str(record.folder_id) if record.folder_id else None,
        "original_filename": record.original_filename,
        "mime_type": record.mime_type,
        "size_bytes": record.size_bytes,
        "uploaded_at": record.uploaded_at.isoformat() if record.uploaded_at else None,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
    }


@bp.get("")
@login_required
def list_trash():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    items = trash.list_trashed_for_owner(user)
    return jsonify({"items": [_trash_payload(r) for r in items]}), 200


@bp.post("/<uuid:file_id>/restore")
@login_required
@csrf.csrf_protect
def restore(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        record = files.get_for_owner(file_id, user, include_trashed=True)
    except FileNotFoundError:
        abort(404, description="File not found.")
    if record.deleted_at is None:
        # Not in trash — treat as 404 to avoid confusing the trash UI.
        abort(404, description="File is not in the trash.")
    restored = trash.restore(record, actor=user)
    return jsonify(_trash_payload(restored)), 200


@bp.delete("/<uuid:file_id>")
@login_required
@csrf.csrf_protect
def hard_delete(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        record = files.get_for_owner(file_id, user, include_trashed=True)
    except FileNotFoundError:
        abort(404, description="File not found.")
    if record.deleted_at is None:
        abort(409, description="Soft-delete the file first before hard-deleting it.")
    trash.hard_delete(record, actor=user, reason="user_purge")
    return ("", 204)
