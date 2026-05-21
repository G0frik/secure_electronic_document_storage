"""Admin department CRUD (Phase 13)."""

from __future__ import annotations

import uuid

from flask import Blueprint, abort, jsonify, request
from pydantic import ValidationError

from app.models.user import Department
from app.schemas.admin import DepartmentCreateRequest, DepartmentRenameRequest
from app.services import csrf, departments
from app.services.departments import (
    DepartmentConflictError,
    DepartmentError,
    DepartmentInUseError,
)
from app.utils.auth_decorators import admin_required, current_user_or_none

bp = Blueprint("admin_departments", __name__, url_prefix="/api/admin/departments")


def _payload(d: Department) -> dict:
    return {
        "id": str(d.id),
        "name": d.name,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _resolve_or_404(dept_id: uuid.UUID) -> Department:
    dept = departments.get(dept_id)
    if dept is None:
        abort(404, description="Department not found.")
    return dept


@bp.get("")
@admin_required
def list_departments():  # type: ignore[no-untyped-def]
    return jsonify({"items": [_payload(d) for d in departments.list_all()]}), 200


@bp.post("")
@admin_required
@csrf.csrf_protect
def create():  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    try:
        payload = DepartmentCreateRequest.model_validate(
            request.get_json(silent=True) or {}
        )
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400
    try:
        dept = departments.create(name=payload.name, actor=actor)
    except DepartmentConflictError as exc:
        return jsonify({"error": "conflict", "message": str(exc)}), 409
    except DepartmentError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    return jsonify(_payload(dept)), 201


@bp.patch("/<uuid:dept_id>")
@admin_required
@csrf.csrf_protect
def rename(dept_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    dept = _resolve_or_404(dept_id)
    try:
        payload = DepartmentRenameRequest.model_validate(
            request.get_json(silent=True) or {}
        )
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "details": exc.errors()}), 400
    try:
        departments.rename(dept=dept, name=payload.name, actor=actor)
    except DepartmentConflictError as exc:
        return jsonify({"error": "conflict", "message": str(exc)}), 409
    except DepartmentError as exc:
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400
    return jsonify(_payload(dept)), 200


@bp.delete("/<uuid:dept_id>")
@admin_required
@csrf.csrf_protect
def delete_route(dept_id: uuid.UUID):  # type: ignore[no-untyped-def]
    actor = current_user_or_none()
    dept = _resolve_or_404(dept_id)
    try:
        departments.delete(dept=dept, actor=actor)
    except DepartmentInUseError as exc:
        return jsonify({"error": "in_use", "message": str(exc)}), 409
    return ("", 204)
