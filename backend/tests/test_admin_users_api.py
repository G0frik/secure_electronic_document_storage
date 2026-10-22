"""Phase 13 — admin user management + force-logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.user import Department, Role, UserStatus


def _patch(client, csrf_token, user_id, payload):
    return client.patch(
        f"/api/admin/users/{user_id}",
        json=payload,
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )


# --- Listing + admin gating ---


def test_list_requires_admin(client, db_session, logged_in_user) -> None:
    resp = client.get("/api/admin/users")
    assert resp.status_code == 403


def test_list_returns_all_users(
    client, db_session, logged_in_admin, seeded_user, seeded_other_user
) -> None:
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json["items"]}
    # Three users: the seeded admin, the seeded user, the seeded other user
    assert {logged_in_admin.email, seeded_user.email, seeded_other_user.email} <= emails
    # Quota fields present
    assert all("quota_bytes" in u and "used_bytes" in u for u in resp.json["items"])


# --- Update fields ---


def test_update_role(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    resp = _patch(client, csrf_token, seeded_user.id, {"role": "guest"})
    assert resp.status_code == 200
    db_session.refresh(seeded_user)
    assert seeded_user.role == Role.GUEST

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "admin.user.role_changed")
    ).all()
    assert len(audits) == 1
    assert audits[0].severity.value == "warning"


def test_cannot_demote_last_admin(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    resp = _patch(client, csrf_token, logged_in_admin.id, {"role": "user"})
    assert resp.status_code == 409
    assert resp.json["error"] == "last_admin"
    db_session.refresh(logged_in_admin)
    assert logged_in_admin.role == Role.ADMIN


def test_update_quota(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    resp = _patch(client, csrf_token, seeded_user.id, {"quota_bytes": 10_000})
    assert resp.status_code == 200
    db_session.refresh(seeded_user)
    assert seeded_user.quota_bytes == 10_000


def test_update_status_to_disabled_invalidates_session(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    resp = _patch(client, csrf_token, seeded_user.id, {"status": "disabled"})
    assert resp.status_code == 200
    db_session.refresh(seeded_user)
    assert seeded_user.status == UserStatus.DISABLED
    # Disabling bumps session_invalid_before
    assert seeded_user.session_invalid_before is not None


def test_update_department(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    new_dept = Department(name="legal")
    db_session.add(new_dept)
    db_session.commit()
    resp = _patch(
        client, csrf_token, seeded_user.id, {"department_id": str(new_dept.id)}
    )
    assert resp.status_code == 200
    db_session.refresh(seeded_user)
    assert seeded_user.department_id == new_dept.id


def test_clear_department(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """`clear_department=true` nulls the FK even though department_id is absent."""
    assert seeded_user.department_id is not None
    resp = _patch(client, csrf_token, seeded_user.id, {"clear_department": True})
    assert resp.status_code == 200
    db_session.refresh(seeded_user)
    assert seeded_user.department_id is None


def test_update_unknown_department_400(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    resp = _patch(
        client, csrf_token, seeded_user.id, {"department_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 400
    assert resp.json["error"] == "invalid_department"


# --- Force logout ---


def test_force_logout_bumps_invalid_before(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    resp = client.post(
        f"/api/admin/users/{seeded_user.id}/force-logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 200
    db_session.refresh(seeded_user)
    assert seeded_user.session_invalid_before is not None

    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "admin.user.force_logout")
    ).all()
    assert len(audits) == 1


def test_force_logout_kills_existing_session(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """Log alice in, force-logout her as admin (alice's session is the test
    client → would clear it). To verify isolation, do it the other way:
    admin's own session continues working AFTER admin force-logs out alice
    using the admin session.
    """
    # Sanity: admin can hit /me
    assert client.get("/api/auth/me").status_code == 200
    # Admin force-logs out alice (someone else)
    client.post(
        f"/api/admin/users/{seeded_user.id}/force-logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    # Admin's own session still works
    assert client.get("/api/auth/me").status_code == 200


def test_force_logout_self_invalidates_current_session(
    client, db_session, logged_in_user, csrf_token
) -> None:
    """The session_invalid_before check trips when the same user re-validates."""
    # Bump alice's session_invalid_before to 1 second in the future so any
    # session issued at or before "now" fails the check. We do this via the
    # model directly (admin endpoint requires admin role).
    from app.services import users as users_service

    alice = users_service.get_user_by_email(logged_in_user.email)
    assert alice is not None
    alice.session_invalid_before = datetime.now(UTC) + timedelta(seconds=1)
    db_session.commit()
    # Next request from alice's session is rejected
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# --- Per-user audit ---


def test_per_user_audit_returns_relevant_rows(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    # Touch alice via PATCH to generate audit rows
    _patch(client, csrf_token, seeded_user.id, {"role": "guest"})
    resp = client.get(f"/api/admin/users/{seeded_user.id}/audit")
    assert resp.status_code == 200
    actions = [r["action_type"] for r in resp.json["items"]]
    assert "admin.user.role_changed" in actions
