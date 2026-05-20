"""Tag endpoints under /api/files/<id>/tags (Phase 10)."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.models.tag import Tag
from app.schemas.tags import TagAddRequest
from app.services import csrf, files, tags
from app.services.files import FileNotFoundError
from app.services.tags import InvalidTagNameError, TooManyTagsError
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("tags", __name__, url_prefix="/api/files")


def _tag_payload(tag: Tag) -> dict:
    return {
        "id": str(tag.id),
        "name": tag.name,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


def _own_file_or_404(file_id: uuid.UUID, user):  # type: ignore[no-untyped-def]
    """Ownership-gated lookup. Tags are an owner-only operation in Phase 10."""
    try:
        return files.get_for_owner(file_id, user)
    except FileNotFoundError:
        abort(404, description="File not found.")


@bp.get("/<uuid:file_id>/tags")
@login_required
def list_tags(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    record = _own_file_or_404(file_id, user)
    rows = tags.list_for_file(record.id)
    return jsonify({"items": [_tag_payload(t) for t in rows]}), 200


@bp.post("/<uuid:file_id>/tags")
@login_required
@csrf.csrf_protect
def add_tags(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    record = _own_file_or_404(file_id, user)
    try:
        payload = TagAddRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        applied = tags.add_to_file(
            file_id=record.id, names=payload.names, actor=user
        )
    except InvalidTagNameError as exc:
        return jsonify({"error": "invalid_tag", "message": str(exc)}), 400
    except TooManyTagsError as exc:
        return jsonify({"error": "too_many_tags", "message": str(exc)}), 409

    return jsonify({"items": [_tag_payload(t) for t in applied]}), 201


@bp.delete("/<uuid:file_id>/tags/<uuid:tag_id>")
@login_required
@csrf.csrf_protect
def remove_tag(file_id: uuid.UUID, tag_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    record = _own_file_or_404(file_id, user)
    tags.remove_from_file(file_id=record.id, tag_id=tag_id, actor=user)
    return ("", 204)
