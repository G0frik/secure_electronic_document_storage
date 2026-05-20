"""Phase 5 — /api/admin/policies CRUD endpoints."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.policy import AccessPolicy
from app.models.user import Department, Role


def _create_body(**overrides):
    body = {
        "role": "user",
        "department_id": None,
        "allowed_max_tier": "internal",
        "allowed_categories": None,
        "denied_categories": None,
        "description": "Test policy.",
    }
    body.update(overrides)
    return body


# --- Auth gating ---


def test_list_policies_requires_login(client) -> None:
    response = client.get("/api/admin/policies")
    assert response.status_code == 401


def test_list_policies_requires_admin(client, db_session, logged_in_user) -> None:
    response = client.get("/api/admin/policies")
    assert response.status_code == 403


def test_create_policy_requires_admin(client, db_session, logged_in_user, csrf_token) -> None:
    response = client.post(
        "/api/admin/policies",
        json=_create_body(),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 403


# --- List ---


def test_list_includes_default_policies(client, db_session, logged_in_admin) -> None:
    response = client.get("/api/admin/policies")
    assert response.status_code == 200
    items = response.json["items"]
    roles = {p["role"] for p in items if p["department_id"] is None}
    assert roles == {"admin", "user", "guest"}


# --- Create ---


def test_create_policy_inserts_and_audits(client, db_session, logged_in_admin, csrf_token) -> None:
    dept = Department(name="finance")
    db_session.add(dept)
    db_session.commit()

    response = client.post(
        "/api/admin/policies",
        json=_create_body(
            role="user",
            department_id=str(dept.id),
            allowed_max_tier="restricted",
            allowed_categories=["salary"],
        ),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.data
    payload = response.json
    assert payload["role"] == "user"
    assert payload["department_id"] == str(dept.id)
    assert payload["allowed_max_tier"] == "restricted"
    assert payload["allowed_categories"] == ["salary"]

    rows = db_session.scalars(
        select(AccessPolicy).where(AccessPolicy.department_id == dept.id)
    ).all()
    assert len(rows) == 1
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "policy.created")
    ).all()
    assert len(audits) == 1


def test_create_policy_validates_payload(client, db_session, logged_in_admin, csrf_token) -> None:
    response = client.post(
        "/api/admin/policies",
        json={"role": "not-a-real-role"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_create_policy_rejects_unknown_department(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    response = client.post(
        "/api/admin/policies",
        json=_create_body(department_id=str(uuid.uuid4())),
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 400


# --- Update ---


def test_update_policy_changes_fields(client, db_session, logged_in_admin, csrf_token) -> None:
    policy = db_session.scalar(
        select(AccessPolicy).where(
            AccessPolicy.role == Role.USER, AccessPolicy.department_id.is_(None)
        )
    )
    assert policy is not None
    response = client.patch(
        f"/api/admin/policies/{policy.id}",
        json={"allowed_max_tier": "internal", "description": "tighter cap"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    db_session.refresh(policy)
    assert policy.allowed_max_tier.value == "internal"
    assert policy.description == "tighter cap"
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "policy.updated")
    ).all()
    assert len(audits) == 1


def test_update_policy_404_for_unknown(client, db_session, logged_in_admin, csrf_token) -> None:
    response = client.patch(
        f"/api/admin/policies/{uuid.uuid4()}",
        json={"allowed_max_tier": "public"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 404


# --- Delete ---


def test_delete_policy_removes_row_and_audits(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    new_dept = Department(name="sales")
    db_session.add(new_dept)
    db_session.commit()
    custom = AccessPolicy(
        role=Role.USER,
        department_id=new_dept.id,
        allowed_max_tier=db_session.scalar(
            select(AccessPolicy).where(AccessPolicy.role == Role.USER, AccessPolicy.department_id.is_(None))
        ).allowed_max_tier,
        description="to delete",
    )
    db_session.add(custom)
    db_session.commit()
    policy_id = custom.id

    response = client.delete(
        f"/api/admin/policies/{policy_id}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 204
    assert db_session.get(AccessPolicy, policy_id) is None
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "policy.deleted")
    ).all()
    assert len(audits) == 1


# --- Matrix preview ---


def test_matrix_endpoint_returns_default_rows(client, db_session, logged_in_admin) -> None:
    response = client.get("/api/admin/policies/_matrix")
    assert response.status_code == 200
    rows = response.json["rows"]
    # 3 default policies present
    assert len(rows) >= 3
    by_role_default = {
        (r["role"], r["allowed_max_tier"]) for r in rows if r["department"] is None
    }
    assert ("admin", "restricted") in by_role_default
    assert ("user", "confidential") in by_role_default
    assert ("guest", "public") in by_role_default
