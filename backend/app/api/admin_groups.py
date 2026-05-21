"""Admin group CRUD + membership API (Phase 13)."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.models.group import Group
from app.schemas.admin import GroupCreateRequest, GroupUpdateRequest
from app.services import admin_users, csrf, groups
from app.services.groups import GroupConflictError, GroupError
from app.utils.auth_decorators import admin_required, current_user_or_none

bp = Blueprint("admin_groups", __name__, url_prefix="/api/admin/groups")


def _group_payload(g: Group, *, with_members: bool = False) -> dict:
    payload = {
        "id": str(g.id),
        "name": g.name,
        "description": g.description,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }
    if with_members:
        payload["members"] = [
            {"id": str(m.id), "email": m.email, "role": m.role.value}
            for m in groups.members_of(g)
        ]
    return payload


def _resolve_or_404(group_id: uuid.UUID) -> Group:
    g = groups.get(group_id)
    if g is None:
        abort(404, description="Group not found.")
    return g


# --- CRUD ---


@bp.get("")
@admin_required
def list_groups():  # type: ignore[no-untyped-def]
    return jsonify({"items": [_group_payload(g) for g in groups.list_all()]}), 200


@bp.post("")
@admin_required
@csrf.csrf_protect
def create():  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    try:
        payload = GroupCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400
    try:
        g = groups.create(name=payload.name, description=payload.description, actor=actor)
    except GroupConflictError as exc:
        return jsonify({"error": "conflict", "message": str(exc)}), 409
    except GroupError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    return jsonify(_group_payload(g)), 201


@bp.get("/<uuid:group_id>")
@admin_required
def get_group(group_id: uuid.UUID):  # type: ignore[no-untyped-def]
    g = _resolve_or_404(group_id)
    return jsonify(_group_payload(g, with_members=True)), 200


@bp.patch("/<uuid:group_id>")
@admin_required
@csrf.csrf_protect
def update(group_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    g = _resolve_or_404(group_id)
    try:
        payload = GroupUpdateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400
    try:
        groups.update(
            group=g,
            name=payload.name,
            description=payload.description,
            clear_description=payload.clear_description,
            actor=actor,
        )
    except GroupConflictError as exc:
        return jsonify({"error": "conflict", "message": str(exc)}), 409
    except GroupError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    return jsonify(_group_payload(g)), 200


@bp.delete("/<uuid:group_id>")
@admin_required
@csrf.csrf_protect
def delete_route(group_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    g = _resolve_or_404(group_id)
    groups.delete(group=g, actor=actor)
    return ("", 204)


# --- Members ---


@bp.get("/<uuid:group_id>/members")
@admin_required
def list_members(group_id: uuid.UUID):  # type: ignore[no-untyped-def]
    g = _resolve_or_404(group_id)
    members = groups.members_of(g)
    return (
        jsonify(
            {
                "items": [
                    {"id": str(m.id), "email": m.email, "role": m.role.value}
                    for m in members
                ]
            }
        ),
        200,
    )


@bp.post("/<uuid:group_id>/members/<uuid:user_id>")
@admin_required
@csrf.csrf_protect
def add_member(group_id: uuid.UUID, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    g = _resolve_or_404(group_id)
    user = admin_users.get(user_id)
    if user is None:
        abort(404, description="User not found.")
    groups.add_member(group=g, user=user, actor=actor)
    return jsonify(_group_payload(g, with_members=True)), 200


@bp.delete("/<uuid:group_id>/members/<uuid:user_id>")
@admin_required
@csrf.csrf_protect
def remove_member(group_id: uuid.UUID, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    g = _resolve_or_404(group_id)
    user = admin_users.get(user_id)
    if user is None:
        abort(404, description="User not found.")
    groups.remove_member(group=g, user=user, actor=actor)
    return ("", 204)
