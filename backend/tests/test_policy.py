"""Phase 5 — tier-based RBAC policy service tests.

Covers:
  - Owner short-circuit (any tier, any classification state)
  - Admin bypass (any tier, any classification state)
  - Tier matrix for the 3 default policies
  - Category whitelist / blacklist
  - Pending classification = default deny
  - Department-scoped policy beats global
  - PolicyEvaluation row written for every check
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.classification import Classification, ClassificationStatus, ClassificationTier
from app.models.file import File
from app.models.policy import AccessPolicy, PolicyDecision, PolicyEvaluation
from app.models.user import Department, Role, User
from app.services import passwords, policy


# --- helpers ---


def _make_file(db_session, owner: User, filename: str = "doc.txt") -> File:
    f = File(
        owner_id=owner.id,
        original_filename=filename,
        storage_key=uuid.uuid4(),
        mime_type="text/plain",
        size_bytes=10,
        sha256="0" * 64,
        wrapped_dek=b"\x00" * 60,
        nonce=b"\x00" * 12,
        auth_tag=b"\x00" * 16,
        kek_version=1,
    )
    db_session.add(f)
    db_session.commit()
    return f


def _classify(
    db_session,
    file: File,
    tier: ClassificationTier,
    *,
    categories: list[str] | None = None,
) -> Classification:
    c = Classification(
        file_id=file.id,
        version=1,
        status=ClassificationStatus.COMPLETED,
        final_tier=tier,
        zero_shot_tier=tier,
        presidio_tier=ClassificationTier.PUBLIC,
        categories_triggered=categories or [],
        classifier_version="v6",
        classified_at=datetime.now(timezone.utc),
    )
    db_session.add(c)
    db_session.commit()
    return c


def _seed_role_user(db_session, role: Role, *, email: str, dept: Department | None = None) -> User:
    u = User(
        email=email,
        password_hash=passwords.hash_password("Password123Test!"),  # noqa: S106
        role=role,
        department_id=dept.id if dept else None,
    )
    db_session.add(u)
    db_session.commit()
    return u


# --- Owner short-circuit ---


def test_owner_always_allowed_even_for_restricted(db_session, seeded_user) -> None:
    f = _make_file(db_session, seeded_user)
    _classify(db_session, f, ClassificationTier.RESTRICTED, categories=["medical records"])

    decision = policy.can_user_access(seeded_user, f)
    assert decision.allowed
    assert decision.reason == policy.REASON_OWNER


def test_owner_allowed_without_classification(db_session, seeded_user) -> None:
    f = _make_file(db_session, seeded_user)
    decision = policy.can_user_access(seeded_user, f)
    assert decision.allowed
    assert decision.reason == policy.REASON_OWNER


# --- Admin bypass ---


def test_admin_bypass(db_session, seeded_admin, seeded_other_user) -> None:
    f = _make_file(db_session, seeded_other_user)
    _classify(db_session, f, ClassificationTier.RESTRICTED)

    decision = policy.can_user_access(seeded_admin, f)
    assert decision.allowed
    assert decision.reason == policy.REASON_ADMIN


# --- Default tier matrix (role → max tier) ---


@pytest.mark.parametrize(
    "role,tier,should_allow",
    [
        # User: max tier = confidential
        (Role.USER, ClassificationTier.PUBLIC, True),
        (Role.USER, ClassificationTier.INTERNAL, True),
        (Role.USER, ClassificationTier.CONFIDENTIAL, True),
        (Role.USER, ClassificationTier.RESTRICTED, False),
        # Guest: max tier = public
        (Role.GUEST, ClassificationTier.PUBLIC, True),
        (Role.GUEST, ClassificationTier.INTERNAL, False),
        (Role.GUEST, ClassificationTier.CONFIDENTIAL, False),
        (Role.GUEST, ClassificationTier.RESTRICTED, False),
    ],
)
def test_tier_matrix(db_session, seeded_admin, role, tier, should_allow) -> None:
    """Walk every (role, tier) cell for the non-admin default policies."""
    user = _seed_role_user(db_session, role, email=f"{role.value}-{tier.value}@docstore.app")
    f = _make_file(db_session, seeded_admin)  # owned by someone ELSE
    _classify(db_session, f, tier)

    decision = policy.can_user_access(user, f)
    assert decision.allowed is should_allow, (
        f"{role.value} vs {tier.value}: expected allowed={should_allow}, "
        f"got {decision.allowed} ({decision.reason})"
    )
    if not should_allow:
        assert decision.reason == policy.REASON_POLICY_DENY_TIER


# --- Pending classification = deny non-owners ---


def test_pending_classification_denies_non_owner(
    db_session, seeded_user, seeded_admin
) -> None:
    f = _make_file(db_session, seeded_admin)
    # no classification row
    decision = policy.can_user_access(seeded_user, f)
    assert not decision.allowed
    assert decision.reason == policy.REASON_NO_CLASSIFICATION


def test_pending_classification_status_denies_non_owner(
    db_session, seeded_user, seeded_admin
) -> None:
    f = _make_file(db_session, seeded_admin)
    pending = Classification(file_id=f.id, version=1, status=ClassificationStatus.PENDING)
    db_session.add(pending)
    db_session.commit()

    decision = policy.can_user_access(seeded_user, f)
    assert not decision.allowed
    assert decision.reason == policy.REASON_NO_CLASSIFICATION


def test_failed_classification_denies_non_owner(
    db_session, seeded_user, seeded_admin
) -> None:
    f = _make_file(db_session, seeded_admin)
    failed = Classification(
        file_id=f.id,
        version=1,
        status=ClassificationStatus.FAILED,
        error_message="boom",
    )
    db_session.add(failed)
    db_session.commit()

    decision = policy.can_user_access(seeded_user, f)
    assert not decision.allowed
    assert decision.reason == policy.REASON_CLASSIFICATION_FAILED


# --- Category whitelist / blacklist ---


def test_denied_category_blocks_even_if_tier_ok(
    db_session, seeded_user, seeded_admin
) -> None:
    """An overlap with denied_categories denies even if tier would allow."""
    # Add a policy that denies the "salary" category for this user's role+dept.
    p = AccessPolicy(
        role=Role.USER,
        department_id=seeded_user.department_id,
        allowed_max_tier=ClassificationTier.CONFIDENTIAL,
        denied_categories=["salary"],
        description="Test: marketing denied salary.",
    )
    db_session.add(p)
    db_session.commit()

    f = _make_file(db_session, seeded_admin)
    _classify(db_session, f, ClassificationTier.CONFIDENTIAL, categories=["salary"])

    decision = policy.can_user_access(seeded_user, f)
    assert not decision.allowed
    assert decision.reason == policy.REASON_POLICY_DENY_CATEGORY
    assert decision.matched_policy_id == p.id


def test_allowed_categories_whitelist(db_session, seeded_user, seeded_admin) -> None:
    """A department-scoped policy with allowed_categories grants RESTRICTED
    only for files in those categories — defines the 'HR sees HR-RESTRICTED'
    pattern from the Phase 5 spec.
    """
    # Move user to an HR department and grant restricted-only-in-hr access.
    hr_dept = Department(name="hr")
    db_session.add(hr_dept)
    db_session.flush()
    seeded_user.department_id = hr_dept.id
    p = AccessPolicy(
        role=Role.USER,
        department_id=hr_dept.id,
        allowed_max_tier=ClassificationTier.RESTRICTED,
        allowed_categories=["salary", "medical records"],
        description="HR may see RESTRICTED if category is HR-related.",
    )
    db_session.add(p)
    db_session.commit()

    # File classified RESTRICTED with a matching category → ALLOWED.
    hr_file = _make_file(db_session, seeded_admin, "salary.csv")
    _classify(db_session, hr_file, ClassificationTier.RESTRICTED, categories=["salary"])
    allow = policy.can_user_access(seeded_user, hr_file)
    assert allow.allowed
    assert allow.reason == policy.REASON_POLICY_ALLOW
    assert allow.matched_policy_id == p.id

    # File classified RESTRICTED with a non-matching category → DENIED.
    other_file = _make_file(db_session, seeded_admin, "credentials.txt")
    _classify(
        db_session,
        other_file,
        ClassificationTier.RESTRICTED,
        categories=["authentication credentials"],
    )
    deny = policy.can_user_access(seeded_user, other_file)
    assert not deny.allowed
    assert deny.reason == policy.REASON_POLICY_DENY_NOT_IN_ALLOWED


# --- Department scope beats global ---


def test_department_scoped_policy_wins_over_global(
    db_session, seeded_user, seeded_admin
) -> None:
    """Department-scoped policy for the user's (role, department) takes
    precedence over the global default policy.
    """
    # Default user policy allows up to CONFIDENTIAL. Add a tighter dept-scoped
    # one that restricts the user's department to INTERNAL.
    tight = AccessPolicy(
        role=Role.USER,
        department_id=seeded_user.department_id,
        allowed_max_tier=ClassificationTier.INTERNAL,
        description="Tighter departmental cap.",
    )
    db_session.add(tight)
    db_session.commit()

    f = _make_file(db_session, seeded_admin)
    _classify(db_session, f, ClassificationTier.CONFIDENTIAL)

    decision = policy.can_user_access(seeded_user, f)
    assert not decision.allowed
    assert decision.reason == policy.REASON_POLICY_DENY_TIER
    assert decision.matched_policy_id == tight.id


# --- PolicyEvaluation row is always written ---


def test_evaluation_row_written_on_allow(db_session, seeded_user, seeded_admin) -> None:
    f = _make_file(db_session, seeded_admin)
    _classify(db_session, f, ClassificationTier.PUBLIC)

    before = len(db_session.scalars(select(PolicyEvaluation)).all())
    policy.can_user_access(seeded_user, f)
    rows = db_session.scalars(select(PolicyEvaluation)).all()
    assert len(rows) == before + 1
    assert rows[-1].decision == PolicyDecision.ALLOW
    assert rows[-1].user_id == seeded_user.id
    assert rows[-1].file_id == f.id


def test_evaluation_row_written_on_deny(db_session, seeded_user, seeded_admin) -> None:
    f = _make_file(db_session, seeded_admin)
    _classify(db_session, f, ClassificationTier.RESTRICTED)

    policy.can_user_access(seeded_user, f)
    rows = db_session.scalars(
        select(PolicyEvaluation).where(PolicyEvaluation.decision == PolicyDecision.DENY)
    ).all()
    assert len(rows) == 1
    assert rows[0].reason == policy.REASON_POLICY_DENY_TIER


# --- Decision dataclass behaviour ---


def test_decision_bool_protocol(db_session, seeded_user) -> None:
    f = _make_file(db_session, seeded_user)
    decision = policy.can_user_access(seeded_user, f)
    assert bool(decision) is True
    if not decision:
        pytest.fail("Decision should evaluate truthy when allowed.")


# --- ensure_default_policies idempotency ---


def test_ensure_default_policies_is_idempotent(db_session) -> None:
    """Re-running the seed helper must not duplicate the 3 defaults."""
    policy.ensure_default_policies()
    policy.ensure_default_policies()
    rows = db_session.scalars(
        select(AccessPolicy).where(AccessPolicy.department_id.is_(None))
    ).all()
    assert len(rows) == 3
    by_role = {p.role for p in rows}
    assert by_role == {Role.ADMIN, Role.USER, Role.GUEST}
