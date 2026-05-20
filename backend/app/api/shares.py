"""Shares API blueprint (Phase 7)."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.extensions import db
from app.models.file import File
from app.models.folder import Folder
from app.models.share import Share, ShareTargetType
from app.models.user import User
from app.schemas.shares import ShareCreateRequest
from app.services import csrf, shares
from app.services.shares import (
    ShareAlreadyExistsError,
    SharePermissionDeniedError,
    ShareRecipientNotFoundError,
    ShareSelfError,
    ShareTargetNotFoundError,
)
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("shares", __name__, url_prefix="/api/shares")


def _share_payload(share: Share) -> dict:
    return {
        "id": str(share.id),
        "target_type": share.target_type.value,
        "target_id": str(share.target_id),
        "granter_id": str(share.granter_id),
        "recipient_id": str(share.recipient_id),
        "permission": share.permission.value,
        "created_at": share.created_at.isoformat() if share.created_at else None,
        "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
    }


def _resolve_target_label(share: Share) -> dict:
    """Look up the target's name / filename so the UI can render the share
    without a follow-up request per share row.
    """
    if share.target_type == ShareTargetType.FILE:
        f = db.session.get(File, share.target_id)
        if f is None:
            return {"label": "(file removed)", "kind": "file"}
        return {"label": f.original_filename, "kind": "file"}
    folder = db.session.get(Folder, share.target_id)
    if folder is None:
        return {"label": "(folder removed)", "kind": "folder"}
    return {"label": folder.name, "kind": "folder"}


def _participant_email(user_id: uuid.UUID) -> str | None:
    user = db.session.get(User, user_id)
    return user.email if user else None


# --- Create ---


@bp.post("")
@login_required
@csrf.csrf_protect
def create():  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    try:
        payload = ShareCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        share = shares.create_share(
            granter=actor,
            target_type=payload.target_type,
            target_id=payload.target_id,
            recipient_email=str(payload.recipient_email),
            permission=payload.permission,
        )
    except ShareSelfError as exc:
        return jsonify({"error": "share_self", "message": str(exc)}), 400
    except ShareRecipientNotFoundError as exc:
        return jsonify({"error": "recipient_not_found", "message": str(exc)}), 404
    except ShareTargetNotFoundError as exc:
        return jsonify({"error": "target_not_found", "message": str(exc)}), 404
    except ShareAlreadyExistsError as exc:
        return jsonify({"error": "already_shared", "message": str(exc)}), 409

    out = _share_payload(share)
    out.update(_resolve_target_label(share))
    out["recipient_email"] = _participant_email(share.recipient_id)
    return jsonify(out), 201


# --- Read ---


@bp.get("/received")
@login_required
def list_received():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    rows = shares.list_received(user)
    items = []
    for share in rows:
        out = _share_payload(share)
        out.update(_resolve_target_label(share))
        out["granter_email"] = _participant_email(share.granter_id)
        items.append(out)
    return jsonify({"items": items}), 200


@bp.get("/granted")
@login_required
def list_granted():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    rows = shares.list_granted(user)
    items = []
    for share in rows:
        out = _share_payload(share)
        out.update(_resolve_target_label(share))
        out["recipient_email"] = _participant_email(share.recipient_id)
        items.append(out)
    return jsonify({"items": items}), 200


# --- Revoke ---


@bp.delete("/<uuid:share_id>")
@login_required
@csrf.csrf_protect
def revoke(share_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    share = shares.get_share(share_id)
    if share is None:
        abort(404, description="Share not found.")
    try:
        shares.revoke_share(share, actor=actor)
    except SharePermissionDeniedError as exc:
        return jsonify({"error": "forbidden", "message": str(exc)}), 403
    return ("", 204)
