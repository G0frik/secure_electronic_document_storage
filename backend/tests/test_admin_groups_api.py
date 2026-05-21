"""Phase 13 — admin departments + groups CRUD + group-targeted policy."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.file import File
from app.models.group import Group, UserGroup
from app.models.policy import AccessPolicy
from app.models.user import Role


# --- Departments ---


def test_departments_crud(client, db_session, logged_in_admin, csrf_token) -> None:
    create = client.post(
        "/api/admin/departments",
        json={"name": "legal"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert create.status_code == 201
    dept_id = create.json["id"]

    listing = client.get("/api/admin/departments")
    assert "legal" in {d["name"] for d in listing.json["items"]}

    rename = client.patch(
        f"/api/admin/departments/{dept_id}",
        json={"name": "Legal"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert rename.status_code == 200
    assert rename.json["name"] == "Legal"

    delete = client.delete(
        f"/api/admin/departments/{dept_id}", headers={"X-CSRF-Token": csrf_token}
    )
    assert delete.status_code == 204


def test_department_with_users_refuses_delete(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """seeded_user is in 'marketing'."""
    dept_id = str(seeded_user.department_id)
    resp = client.delete(
        f"/api/admin/departments/{dept_id}", headers={"X-CSRF-Token": csrf_token}
    )
    assert resp.status_code == 409
    assert resp.json["error"] == "in_use"


def test_department_create_conflict(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    client.post(
        "/api/admin/departments",
        json={"name": "dup"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    dup = client.post(
        "/api/admin/departments",
        json={"name": "dup"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert dup.status_code == 409


def test_departments_require_admin(client, db_session, logged_in_user, csrf_token) -> None:
    assert client.get("/api/admin/departments").status_code == 403


# --- Groups ---


def test_groups_crud(client, db_session, logged_in_admin, csrf_token) -> None:
    create = client.post(
        "/api/admin/groups",
        json={"name": "leads", "description": "team leads"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert create.status_code == 201
    group_id = create.json["id"]

    rename = client.patch(
        f"/api/admin/groups/{group_id}",
        json={"name": "Team Leads"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert rename.status_code == 200
    assert rename.json["name"] == "Team Leads"

    client.delete(f"/api/admin/groups/{group_id}", headers={"X-CSRF-Token": csrf_token})
    assert db_session.scalar(select(Group).where(Group.id == uuid.UUID(group_id))) is None


def test_group_membership(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    group = client.post(
        "/api/admin/groups",
        json={"name": "engineering-leads"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    ).json

    add = client.post(
        f"/api/admin/groups/{group['id']}/members/{seeded_user.id}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert add.status_code == 200
    member_emails = {m["email"] for m in add.json["members"]}
    assert seeded_user.email in member_emails

    # Idempotent: adding twice is fine
    again = client.post(
        f"/api/admin/groups/{group['id']}/members/{seeded_user.id}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert again.status_code == 200
    rows = db_session.scalars(
        select(UserGroup).where(
            UserGroup.group_id == uuid.UUID(group["id"]),
            UserGroup.user_id == seeded_user.id,
        )
    ).all()
    assert len(rows) == 1

    remove = client.delete(
        f"/api/admin/groups/{group['id']}/members/{seeded_user.id}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert remove.status_code == 204


# --- Group-targeted policy resolution ---


def _classify_file(db_session, file_id, tier):
    existing = db_session.scalar(
        select(Classification).where(Classification.file_id == file_id)
    )
    if existing is None:
        existing = Classification(file_id=file_id, version=1)
        db_session.add(existing)
    existing.status = ClassificationStatus.COMPLETED
    existing.final_tier = tier
    existing.zero_shot_tier = tier
    existing.presidio_tier = ClassificationTier.PUBLIC
    existing.categories_triggered = []
    existing.classifier_version = "v6"
    existing.classified_at = datetime.now(timezone.utc)
    db_session.commit()
    return existing


def _make_file_for(db_session, owner) -> File:
    f = File(
        owner_id=owner.id,
        original_filename="x.txt",
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(f)
    db_session.commit()
    return f


def test_group_policy_grants_higher_tier(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """Default user policy caps at CONFIDENTIAL; a group-targeted policy
    grants RESTRICTED to members. The user should be allowed to read a
    RESTRICTED file owned by someone else when in the group.
    """
    from app.services import policy

    # File owned by admin, classified RESTRICTED
    target = _make_file_for(db_session, logged_in_admin)
    _classify_file(db_session, target.id, ClassificationTier.RESTRICTED)

    # Without group, seeded_user (default user policy = ≤ confidential) → deny
    decision = policy.can_user_access(seeded_user, target, record=False)
    assert not decision.allowed
    assert decision.reason == "tier_exceeds_policy"

    # Mint a group + group-targeted policy that allows RESTRICTED
    group = Group(name="cleared")
    db_session.add(group)
    db_session.flush()
    db_session.add(UserGroup(user_id=seeded_user.id, group_id=group.id))
    db_session.add(
        AccessPolicy(
            role=Role.USER,
            group_id=group.id,
            allowed_max_tier=ClassificationTier.RESTRICTED,
            description="cleared group",
        )
    )
    db_session.commit()

    decision2 = policy.can_user_access(seeded_user, target, record=False)
    assert decision2.allowed
    assert decision2.reason == "policy_allow"


def test_group_policy_max_permissive_wins(
    client, db_session, logged_in_admin, seeded_user, csrf_token
) -> None:
    """User in two groups; the more-permissive group policy wins."""
    from app.services import policy

    target = _make_file_for(db_session, logged_in_admin)
    _classify_file(db_session, target.id, ClassificationTier.RESTRICTED)

    g_low = Group(name="low")
    g_high = Group(name="high")
    db_session.add_all([g_low, g_high])
    db_session.flush()
    db_session.add_all(
        [
            UserGroup(user_id=seeded_user.id, group_id=g_low.id),
            UserGroup(user_id=seeded_user.id, group_id=g_high.id),
            AccessPolicy(
                role=Role.USER,
                group_id=g_low.id,
                allowed_max_tier=ClassificationTier.INTERNAL,
                description="low",
            ),
            AccessPolicy(
                role=Role.USER,
                group_id=g_high.id,
                allowed_max_tier=ClassificationTier.RESTRICTED,
                description="high",
            ),
        ]
    )
    db_session.commit()

    decision = policy.can_user_access(seeded_user, target, record=False)
    assert decision.allowed, decision.reason


def test_group_audit_recorded(
    client, db_session, logged_in_admin, csrf_token
) -> None:
    client.post(
        "/api/admin/groups",
        json={"name": "audited"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    audits = db_session.scalars(
        select(AuditLog).where(AuditLog.action_type == "admin.group.created")
    ).all()
    assert len(audits) == 1
