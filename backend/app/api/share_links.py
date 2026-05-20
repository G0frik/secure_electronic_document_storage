"""Authenticated share-link API (Phase 8). Owner of a file or admin can
mint links, list their own minted links, and revoke them.

Public consumer endpoints live in `api/public_share_links.py`.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.extensions import db
from app.models.file import File
from app.models.share_link import ShareLink
from app.schemas.share_links import ShareLinkCreateRequest
from app.services import csrf, share_links
from app.services.share_links import (
    ShareLinkClassificationPendingError,
    ShareLinkError,
    ShareLinkPermissionDeniedError,
    ShareLinkTierBlockedError,
)
from app.utils.auth_decorators import current_user_or_none, login_required

bp = Blueprint("share_links", __name__, url_prefix="/api/share-links")


def _link_payload(link: ShareLink, *, token: str | None = None) -> dict:
    file_row = db.session.get(File, link.file_id)
    return {
        "id": str(link.id),
        "file_id": str(link.file_id),
        "filename": file_row.original_filename if file_row else None,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "max_uses": link.max_uses,
        "use_count": link.use_count,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
        "created_by_id": str(link.created_by_id) if link.created_by_id else None,
        # `token` only present in the create response. Never re-served.
        "token": token,
    }


@bp.post("")
@login_required
@csrf.csrf_protect
def create():  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    try:
        payload = ShareLinkCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        minted = share_links.create_link(
            creator=actor,
            file_id=payload.file_id,
            expires_at=payload.expires_at,
            max_uses=payload.max_uses,
            force_for_restricted=payload.force_for_restricted,
        )
    except ShareLinkTierBlockedError as exc:
        return jsonify({"error": "tier_blocked", "message": str(exc)}), 403
    except ShareLinkClassificationPendingError as exc:
        return jsonify({"error": "classification_pending", "message": str(exc)}), 409
    except ShareLinkError as exc:
        return jsonify({"error": "share_link_error", "message": str(exc)}), 400

    return jsonify(_link_payload(minted.link, token=minted.token)), 201


@bp.get("/granted")
@login_required
def list_granted():  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    rows = share_links.list_granted(user)
    return jsonify({"items": [_link_payload(r) for r in rows]}), 200


@bp.delete("/<uuid:link_id>")
@login_required
@csrf.csrf_protect
def revoke(link_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    link = share_links.get_by_id(link_id)
    if link is None:
        abort(404, description="Share link not found.")
    try:
        share_links.revoke_link(link, actor=actor)
    except ShareLinkPermissionDeniedError as exc:
        return jsonify({"error": "forbidden", "message": str(exc)}), 403
    return ("", 204)
