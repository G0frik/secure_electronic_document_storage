"""Admin CRUD for access policies. All endpoints require role=admin.

Every mutation writes an audit row. Reads do not — listing the policy table
is just configuration browsing.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.audit import AuditSeverity
from app.models.classification import ClassificationTier
from app.models.policy import AccessPolicy
from app.models.user import Department, Role
from app.schemas.policy import PolicyCreateRequest, PolicyUpdateRequest
from app.services import audit, csrf
from app.utils.auth_decorators import admin_required, current_user_or_none

bp = Blueprint("admin_policies", __name__, url_prefix="/api/admin/policies")


def _policy_payload(p: AccessPolicy) -> dict:
    return {
        "id": str(p.id),
        "role": p.role.value,
        "department_id": str(p.department_id) if p.department_id else None,
        "department": p.department.name if p.department else None,
        "allowed_max_tier": p.allowed_max_tier.value,
        "allowed_categories": p.allowed_categories,
        "denied_categories": p.denied_categories,
        "description": p.description,
        "created_by_id": str(p.created_by_id) if p.created_by_id else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@bp.get("")
@admin_required
def list_policies():  # type: ignore[no-untyped-def]
    rows = db.session.scalars(
        select(AccessPolicy).order_by(
            AccessPolicy.role,
            AccessPolicy.department_id.is_(None).desc(),
            AccessPolicy.created_at,
        )
    ).all()
    return jsonify({"items": [_policy_payload(p) for p in rows]}), 200


@bp.post("")
@admin_required
@csrf.csrf_protect
def create_policy():  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    try:
        payload = PolicyCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    if payload.department_id is not None:
        dept = db.session.get(Department, payload.department_id)
        if dept is None:
            return jsonify({"error": "invalid_request", "message": "Unknown department."}), 400

    policy = AccessPolicy(
        role=payload.role,
        department_id=payload.department_id,
        allowed_max_tier=ClassificationTier(payload.allowed_max_tier.value),
        allowed_categories=payload.allowed_categories,
        denied_categories=payload.denied_categories,
        description=payload.description,
        created_by_id=actor.id,
    )
    db.session.add(policy)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "conflict", "message": "Policy already exists."}), 409

    audit.record(
        "policy.created",
        actor=actor,
        target_type="access_policy",
        target_id=policy.id,
        metadata={
            "role": policy.role.value,
            "department_id": str(policy.department_id) if policy.department_id else None,
            "allowed_max_tier": policy.allowed_max_tier.value,
            "allowed_categories": policy.allowed_categories,
            "denied_categories": policy.denied_categories,
        },
        severity=AuditSeverity.INFO,
    )
    return jsonify(_policy_payload(policy)), 201


@bp.get("/<uuid:policy_id>")
@admin_required
def get_policy(policy_id: uuid.UUID):  # type: ignore[no-untyped-def]
    policy = db.session.get(AccessPolicy, policy_id)
    if policy is None:
        abort(404, description="Policy not found.")
    return jsonify(_policy_payload(policy)), 200


@bp.patch("/<uuid:policy_id>")
@admin_required
@csrf.csrf_protect
def update_policy(policy_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    policy = db.session.get(AccessPolicy, policy_id)
    if policy is None:
        abort(404, description="Policy not found.")

    try:
        payload = PolicyUpdateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    before = _policy_payload(policy)

    if payload.allowed_max_tier is not None:
        policy.allowed_max_tier = ClassificationTier(payload.allowed_max_tier.value)
    if payload.allowed_categories is not None:
        policy.allowed_categories = payload.allowed_categories
    elif payload.clear_allowed_categories:
        policy.allowed_categories = None
    if payload.denied_categories is not None:
        policy.denied_categories = payload.denied_categories
    elif payload.clear_denied_categories:
        policy.denied_categories = None
    if payload.description is not None:
        policy.description = payload.description
    elif payload.clear_description:
        policy.description = None
    if payload.clear_department:
        policy.department_id = None

    db.session.commit()

    audit.record(
        "policy.updated",
        actor=actor,
        target_type="access_policy",
        target_id=policy.id,
        metadata={"before": before, "after": _policy_payload(policy)},
        severity=AuditSeverity.INFO,
    )
    return jsonify(_policy_payload(policy)), 200


@bp.delete("/<uuid:policy_id>")
@admin_required
@csrf.csrf_protect
def delete_policy(policy_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    policy = db.session.get(AccessPolicy, policy_id)
    if policy is None:
        abort(404, description="Policy not found.")

    snapshot = _policy_payload(policy)
    db.session.delete(policy)
    db.session.commit()

    audit.record(
        "policy.deleted",
        actor=actor,
        target_type="access_policy",
        target_id=policy_id,
        metadata={"deleted": snapshot},
        severity=AuditSeverity.WARNING,
    )
    return ("", 204)


# --- Read-only convenience: who can access what right now? ---


@bp.get("/_matrix")
@admin_required
def matrix():  # type: ignore[no-untyped-def]
    """Return the (role, department) → allowed_max_tier matrix for the admin UI.

    Department=null rows mean "default for that role". Useful for the
    "what can role X see?" preview in Phase 14's policy editor.
    """
    rows = db.session.scalars(select(AccessPolicy)).all()
    matrix_view = []
    for r in rows:
        matrix_view.append(
            {
                "role": r.role.value,
                "department_id": str(r.department_id) if r.department_id else None,
                "department": r.department.name if r.department else None,
                "allowed_max_tier": r.allowed_max_tier.value,
                "allowed_categories": r.allowed_categories,
                "denied_categories": r.denied_categories,
            }
        )
    # Stable ordering: role then department-default first.
    role_order = {Role.ADMIN.value: 0, Role.USER.value: 1, Role.GUEST.value: 2}
    matrix_view.sort(
        key=lambda r: (role_order.get(r["role"], 99), r["department"] or "")
    )
    return jsonify({"rows": matrix_view}), 200
