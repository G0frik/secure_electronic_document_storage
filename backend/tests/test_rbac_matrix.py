"""Phase 16 — explicit RBAC matrix test.

The full (role, tier) matrix walked end-to-end through the HTTP layer
(`GET /api/files/<id>/download`). One owner uploads + classifies the file;
a SECOND user with the role under test attempts to download. The expected
decision per cell is derived from the default policy table:

    role     allowed_max_tier
    admin    restricted     (also has admin bypass — every cell allows)
    user     confidential
    guest    public

The original Phase-5 tests cover this in pieces (`test_policy.py` walks
the service directly, `test_files_api.py` checks a couple of HTTP cells).
This file is the consolidated view: one parametrized test,
12 cells, every row labeled.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.file import File
from app.models.policy import PolicyEvaluation
from app.models.user import Department, Role, User
from app.services import crypto, passwords, storage


# Cells of the matrix. `expected_allowed=True` means the role can download;
# `False` means a 403 access_denied. Reason codes match what the API
# returns under the default policies seeded by `ensure_default_policies`.
_MATRIX: list[tuple[str, str, bool, str | None]] = [
    # (role, tier,                  allowed, reason_on_deny)
    ("admin", "public",             True,   None),
    ("admin", "internal",           True,   None),
    ("admin", "confidential",       True,   None),
    ("admin", "restricted",         True,   None),
    ("user",  "public",             True,   None),
    ("user",  "internal",           True,   None),
    ("user",  "confidential",       True,   None),
    ("user",  "restricted",         False,  "tier_exceeds_policy"),
    ("guest", "public",             True,   None),
    ("guest", "internal",           False,  "tier_exceeds_policy"),
    ("guest", "confidential",       False,  "tier_exceeds_policy"),
    ("guest", "restricted",         False,  "tier_exceeds_policy"),
]


_PLAINTEXT = b"matrix-test-payload"


def _seed_file(db_session, owner: User, tier: ClassificationTier) -> File:
    """Insert a real (encrypted) file owned by *owner*, classified at *tier*."""
    blob = crypto.encrypt_file(_PLAINTEXT)
    storage_key = uuid.uuid4()
    import io as _io

    storage.put(
        str(storage_key),
        _io.BytesIO(blob.ciphertext),
        length=len(blob.ciphertext),
        content_type="application/octet-stream",
    )
    f = File(
        owner_id=owner.id,
        original_filename=f"matrix-{tier.value}.txt",
        storage_key=storage_key,
        mime_type="text/plain",
        size_bytes=len(_PLAINTEXT),
        sha256="0" * 64,
        wrapped_dek=blob.wrapped_dek,
        nonce=blob.nonce,
        auth_tag=blob.auth_tag,
        kek_version=blob.kek_version,
    )
    db_session.add(f)
    db_session.flush()
    db_session.add(
        Classification(
            file_id=f.id,
            version=1,
            status=ClassificationStatus.COMPLETED,
            final_tier=tier,
            zero_shot_tier=tier,
            classifier_version="matrix-test",
            classified_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    return f


def _seed_user(db_session, *, email: str, role: Role) -> User:
    """A second user (the *reader*) under test."""
    user = User(
        email=email,
        password_hash=passwords.hash_password("Password123Test!"),  # noqa: S106
        role=role,
        department_id=None,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.mark.parametrize(("role_str", "tier_str", "expected_allowed", "deny_reason"), _MATRIX)
def test_rbac_matrix(
    client,
    db_session,
    csrf_token,
    role_str: str,
    tier_str: str,
    expected_allowed: bool,
    deny_reason: str | None,
) -> None:
    """One row of the (role × tier) policy matrix: every cell exercised
    through the live HTTP download endpoint with a real AES-GCM encrypted
    blob in MinIO.
    """
    role = Role(role_str)
    tier = ClassificationTier(tier_str)

    # Owner is always the same admin who uploads the file. We give them
    # a department so dept-scoped policies could be wired later.
    dept = Department(name=f"dept-{tier_str}")
    db_session.add(dept)
    db_session.flush()
    owner = User(
        email=f"owner-{tier_str}@docstore.app",
        password_hash=passwords.hash_password("OwnerPassword123!"),  # noqa: S106
        role=Role.ADMIN,
        department_id=dept.id,
    )
    db_session.add(owner)
    db_session.commit()

    file_record = _seed_file(db_session, owner, tier)

    # Reader = a *different* user with the role under test. Fresh email
    # per row so we don't trip the unique constraint across parametrize iterations.
    reader = _seed_user(
        db_session, email=f"reader-{role_str}-{tier_str}@docstore.app", role=role
    )

    response = client.post(
        "/api/auth/login",
        json={"email": reader.email, "password": "Password123Test!"},
        headers={"X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.data

    # Hit the download endpoint as the reader.
    dl = client.get(f"/api/files/{file_record.id}/download")

    if expected_allowed:
        assert dl.status_code == 200, (
            f"({role_str}, {tier_str}) expected ALLOW but got {dl.status_code}: {dl.data!r}"
        )
        assert dl.data == _PLAINTEXT
    else:
        assert dl.status_code == 403, (
            f"({role_str}, {tier_str}) expected DENY but got {dl.status_code}: {dl.data!r}"
        )
        assert dl.json["error"] == "access_denied"
        assert dl.json["reason"] == deny_reason
        # Tier echoed back so the SPA can render "this file is classified X".
        assert dl.json["tier"] == tier_str

    # Every download decision (allow OR deny) MUST have written a
    # PolicyEvaluation row — the per-decision audit table Phase 5 introduced.
    evals = db_session.scalars(
        select(PolicyEvaluation).where(PolicyEvaluation.file_id == file_record.id)
    ).all()
    assert evals, (
        f"({role_str}, {tier_str}) expected a PolicyEvaluation row, found none"
    )

    # Deny rows ALWAYS also write an audit_log entry; allows do not (admin
    # and policy-allow are logged only at the audit-noisy level — see
    # services/policy.py).
    if not expected_allowed:
        deny_audits = db_session.scalars(
            select(AuditLog).where(
                AuditLog.action_type == "policy.decision.deny",
                AuditLog.target_id == file_record.id,
            )
        ).all()
        assert deny_audits, (
            f"({role_str}, {tier_str}) DENY must emit a policy.decision.deny audit row"
        )
