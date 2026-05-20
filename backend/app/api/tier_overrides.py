"""Tier-override request endpoints (Phase 10).

User-facing under /api/files/<id>/tier-override-requests; admin
queue + approve/deny under /api/admin/tier-override-requests.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.models.classification import ClassificationTier
from app.models.tier_override import OverrideStatus, TierOverrideRequest
from app.schemas.tier_overrides import (
    TierOverrideCreateRequest,
    TierOverrideDecisionRequest,
)
from app.services import csrf, files, tier_overrides
from app.services.files import FileNotFoundError
from app.services.tier_overrides import (
    NoClassificationError,
    NotPendingError,
    PendingRequestExistsError,
    SameTierError,
    TierOverrideError,
)
from app.utils.auth_decorators import (
    admin_required,
    current_user_or_none,
    login_required,
)

user_bp = Blueprint(
    "tier_overrides_user", __name__, url_prefix="/api/files"
)
admin_bp = Blueprint(
    "tier_overrides_admin",
    __name__,
    url_prefix="/api/admin/tier-override-requests",
)


def _payload(req: TierOverrideRequest) -> dict:
    return {
        "id": str(req.id),
        "file_id": str(req.file_id),
        "filename": req.file.original_filename if req.file else None,
        "classification_id": (
            str(req.classification_id) if req.classification_id else None
        ),
        "requested_by_id": str(req.requested_by_id),
        "requested_by_email": req.requested_by.email if req.requested_by else None,
        "current_tier": req.current_tier.value,
        "requested_tier": req.requested_tier.value,
        "justification": req.justification,
        "status": req.status.value,
        "reviewed_by_id": str(req.reviewed_by_id) if req.reviewed_by_id else None,
        "reviewed_by_email": req.reviewed_by.email if req.reviewed_by else None,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "decision_reason": req.decision_reason,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


# --- Owner-facing endpoints ---


@user_bp.post("/<uuid:file_id>/tier-override-requests")
@login_required
@csrf.csrf_protect
def create_request(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    user = current_user_or_none()
    try:
        record = files.get_for_owner(file_id, user)
    except FileNotFoundError:
        abort(404, description="File not found.")

    try:
        payload = TierOverrideCreateRequest.model_validate(
            request.get_json(silent=True) or {}
        )
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        req = tier_overrides.create_request(
            file=record,
            requested_tier=ClassificationTier(payload.requested_tier.value),
            justification=payload.justification,
            actor=user,
        )
    except NoClassificationError as exc:
        return jsonify({"error": "classification_pending", "message": str(exc)}), 409
    except SameTierError as exc:
        return jsonify({"error": "same_tier", "message": str(exc)}), 400
    except PendingRequestExistsError as exc:
        return jsonify({"error": "already_pending", "message": str(exc)}), 409
    except TierOverrideError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400

    return jsonify(_payload(req)), 201


@user_bp.get("/<uuid:file_id>/tier-override-requests")
@login_required
def list_for_file(file_id: uuid.UUID):  # type: ignore[no-untyped-def]
    """Owner or admin can see the request history for a file."""
    user = current_user_or_none()
    record = files.get_by_id(file_id)
    if record is None:
        abort(404, description="File not found.")
    if record.owner_id != user.id and not user.is_admin:
        abort(404, description="File not found.")

    rows = tier_overrides.list_for_file(record.id)
    return jsonify({"items": [_payload(r) for r in rows]}), 200


# --- Admin queue + approve/deny ---


@admin_bp.get("")
@admin_required
def list_pending():  # type: ignore[no-untyped-def]
    """Default: all pending. `?status=approved|denied|pending|all` toggles."""
    status_arg = (request.args.get("status") or "pending").lower()
    if status_arg == "all":
        rows = _list_all_admin()
    elif status_arg == "pending":
        rows = tier_overrides.list_pending()
    else:
        try:
            target = OverrideStatus(status_arg)
        except ValueError:
            return jsonify({"error": "invalid_request", "message": "Bad status."}), 400
        rows = _list_by_status(target)
    return jsonify({"items": [_payload(r) for r in rows]}), 200


def _list_by_status(status: OverrideStatus) -> list[TierOverrideRequest]:
    from sqlalchemy import select

    from app.extensions import db

    return list(
        db.session.scalars(
            select(TierOverrideRequest)
            .where(TierOverrideRequest.status == status)
            .order_by(TierOverrideRequest.created_at.desc())
        )
    )


def _list_all_admin() -> list[TierOverrideRequest]:
    from sqlalchemy import select

    from app.extensions import db

    return list(
        db.session.scalars(
            select(TierOverrideRequest).order_by(
                TierOverrideRequest.created_at.desc()
            )
        )
    )


@admin_bp.post("/<uuid:request_id>/approve")
@admin_required
@csrf.csrf_protect
def approve(request_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    req = tier_overrides.get_by_id(request_id)
    if req is None:
        abort(404, description="Override request not found.")

    try:
        payload = TierOverrideDecisionRequest.model_validate(
            request.get_json(silent=True) or {}
        )
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        tier_overrides.approve(
            req, reviewer=actor, decision_reason=payload.decision_reason
        )
    except NotPendingError as exc:
        return jsonify({"error": "not_pending", "message": str(exc)}), 409
    return jsonify(_payload(req)), 200


@admin_bp.post("/<uuid:request_id>/deny")
@admin_required
@csrf.csrf_protect
def deny(request_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    req = tier_overrides.get_by_id(request_id)
    if req is None:
        abort(404, description="Override request not found.")

    try:
        payload = TierOverrideDecisionRequest.model_validate(
            request.get_json(silent=True) or {}
        )
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        tier_overrides.deny(
            req, reviewer=actor, decision_reason=payload.decision_reason
        )
    except NotPendingError as exc:
        return jsonify({"error": "not_pending", "message": str(exc)}), 409
    return jsonify(_payload(req)), 200
