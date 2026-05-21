"""Admin user management API (Phase 13)."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.models.user import Role, User, UserStatus
from app.schemas.admin import UserUpdateRequest
from app.services import admin_users, csrf
from app.services.admin_users import (
    AdminUserError,
    LastAdminError,
    UnknownDepartmentError,
)
from app.utils.auth_decorators import (
    admin_required,
    current_user_or_none,
)

bp = Blueprint("admin_users", __name__, url_prefix="/api/admin/users")


def _user_payload(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "role": u.role.value,
        "status": u.status.value,
        "is_manager": u.is_manager,
        "department_id": str(u.department_id) if u.department_id else None,
        "department": u.department.name if u.department else None,
        "quota_bytes": u.quota_bytes,
        "used_bytes": u.used_bytes,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": (
            u.last_login_at.isoformat() if u.last_login_at else None
        ),
        "session_invalid_before": (
            u.session_invalid_before.isoformat() if u.session_invalid_before else None
        ),
    }


def _resolve_or_404(user_id: uuid.UUID) -> User:
    target = admin_users.get(user_id)
    if target is None:
        abort(404, description="User not found.")
    return target


@bp.get("")
@admin_required
def list_users():  # type: ignore[no-untyped-def]
    return jsonify({"items": [_user_payload(u) for u in admin_users.list_users()]}), 200


@bp.get("/<uuid:user_id>")
@admin_required
def get_user(user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return jsonify(_user_payload(_resolve_or_404(user_id))), 200


@bp.patch("/<uuid:user_id>")
@admin_required
@csrf.csrf_protect
def update_user(user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    target = _resolve_or_404(user_id)
    try:
        payload = UserUpdateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400

    try:
        if payload.role is not None:
            admin_users.update_role(target=target, new_role=payload.role, actor=actor)
        if payload.is_manager is not None:
            admin_users.update_is_manager(
                target=target, is_manager=payload.is_manager, actor=actor
            )
        if payload.clear_department:
            admin_users.update_department(
                target=target, department_id=None, actor=actor
            )
        elif payload.department_id is not None:
            admin_users.update_department(
                target=target, department_id=payload.department_id, actor=actor
            )
        if payload.quota_bytes is not None:
            admin_users.update_quota(
                target=target, quota_bytes=payload.quota_bytes, actor=actor
            )
        if payload.status is not None:
            admin_users.update_status(
                target=target, new_status=payload.status, actor=actor
            )
    except LastAdminError as exc:
        return jsonify({"error": "last_admin", "message": str(exc)}), 409
    except UnknownDepartmentError as exc:
        return jsonify({"error": "invalid_department", "message": str(exc)}), 400
    except AdminUserError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400

    return jsonify(_user_payload(target)), 200


@bp.post("/<uuid:user_id>/force-logout")
@admin_required
@csrf.csrf_protect
def force_logout(user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    target = _resolve_or_404(user_id)
    admin_users.force_logout(target=target, actor=actor)
    return jsonify(_user_payload(target)), 200


@bp.get("/<uuid:user_id>/audit")
@admin_required
def user_audit(user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    target = _resolve_or_404(user_id)
    try:
        limit = max(1, min(int(request.args.get("limit", 100)), 1000))
    except ValueError:
        limit = 100
    rows = admin_users.audit_for(target, limit=limit)
    return (
        jsonify(
            {
                "items": [
                    {
                        "id": str(r.id),
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                        "action_type": r.action_type,
                        "severity": r.severity.value if hasattr(r.severity, "value") else str(r.severity),
                        "actor_user_id": (
                            str(r.actor_user_id) if r.actor_user_id else None
                        ),
                        "actor_ip": r.actor_ip,
                        "target_type": r.target_type,
                        "target_id": str(r.target_id) if r.target_id else None,
                        "metadata": r.event_metadata,
                    }
                    for r in rows
                ],
                "count": len(rows),
            }
        ),
        200,
    )
