"""Folders API blueprint (Phase 7)."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.models.folder import Folder
from app.schemas.folders import FolderCreateRequest
from app.services import csrf, folders
from app.services.folders import (
    FolderConflictError,
    FolderNotEmptyError,
    FolderNotFoundError,
    InvalidParentError,
)
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("folders", __name__, url_prefix="/api/folders")


def _folder_payload(f: Folder) -> dict:
    return {
        "id": str(f.id),
        "name": f.name,
        "owner_id": str(f.owner_id),
        "parent_id": str(f.parent_id) if f.parent_id else None,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


@bp.get("")
@login_required
def list_folders():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    rows = folders.list_for_owner(user)
    return jsonify({"items": [_folder_payload(f) for f in rows]}), 200


@bp.post("")
@login_required
@csrf.csrf_protect
def create():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        payload = FolderCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        folder = folders.create_folder(
            owner=user, name=payload.name, parent_id=payload.parent_id
        )
    except InvalidParentError as exc:
        return jsonify({"error": "invalid_parent", "message": str(exc)}), 400
    except FolderConflictError as exc:
        return jsonify({"error": "folder_exists", "message": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400

    return jsonify(_folder_payload(folder)), 201


@bp.get("/<uuid:folder_id>")
@login_required
def get_folder_route(folder_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        folder = folders.get_for_owner(folder_id, user)
    except FolderNotFoundError:
        abort(404, description="Folder not found.")
    return jsonify(_folder_payload(folder)), 200


@bp.delete("/<uuid:folder_id>")
@login_required
@csrf.csrf_protect
def delete_folder_route(folder_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        folder = folders.get_for_owner(folder_id, user)
    except FolderNotFoundError:
        abort(404, description="Folder not found.")
    try:
        folders.delete_folder(folder, actor=user)
    except FolderNotEmptyError as exc:
        return jsonify({"error": "folder_not_empty", "message": str(exc)}), 409
    return ("", 204)
