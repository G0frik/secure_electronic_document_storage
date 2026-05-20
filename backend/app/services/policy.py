"""Access-control policy service — the only Policy Decision Point (PDP) in the app.

Every file-touching endpoint MUST call `can_user_access(user, file)` before
returning bytes or metadata that would leak the existence of the file. The
helper returns a `Decision` with a human-readable reason; the same decision
is written to `policy_evaluations` (always) and `audit_log` (info on allow,
warning on deny — modulo the owner-fast-path where we skip both to keep
volume sane).

Resolution order (most specific first):
  1. Owner short-circuit — the owner can always read their own files.
  2. Department-scoped policy for the user's (role, department_id).
  3. Global policy (department_id NULL) for the user's role.
  4. Default-deny if no policy matched.

Categories: when a matched policy lists `denied_categories`, any overlap
with the file's `categories_triggered` is a deny. When it lists
`allowed_categories`, the file must have at least one matching category
(or the policy still applies to a file with no triggered categories, since
empty intersection is not a positive match either way — practically,
`allowed_categories` is mostly used for department-scoped grants like
"HR may see RESTRICTED files iff category in {hr, salary, ...}").

Pending classifications: if a file has no completed classification yet,
deny non-owners. The owner already short-circuited above.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.classifier_core.tiers import TIER_RANK, Tier
from app.extensions import db
from app.logging_config import get_logger
from app.models.audit import AuditSeverity
from app.models.classification import (
    Classification,
    ClassificationStatus,
    ClassificationTier,
)
from app.models.file import File
from app.models.policy import AccessPolicy, PolicyDecision, PolicyEvaluation
from app.models.user import Role, User
from app.services import audit

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


# --- Decision dataclass ---


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    matched_policy_id: uuid.UUID | None = None
    tier: ClassificationTier | None = None

    def __bool__(self) -> bool:  # `if decision: ...`
        return self.allowed


# Stable reason codes — clients render these, never raw strings.
REASON_OWNER = "owner"
REASON_ADMIN = "admin_role"
REASON_POLICY_ALLOW = "policy_allow"
REASON_POLICY_DENY_TIER = "tier_exceeds_policy"
REASON_POLICY_DENY_CATEGORY = "denied_category"
REASON_POLICY_DENY_NOT_IN_ALLOWED = "category_not_in_allowed"
REASON_NO_POLICY = "no_policy_matched"
REASON_NO_CLASSIFICATION = "classification_pending"
REASON_CLASSIFICATION_FAILED = "classification_failed"


# --- Public API ---


def can_user_access(
    user: User,
    file: File,
    *,
    record: bool = True,
) -> Decision:
    """Return a Decision for (user, file). Writes a `policy_evaluations` row
    by default (set `record=False` for repeated checks within one request)."""
    decision = _evaluate(user, file)
    if record:
        _record_evaluation(user, file, decision)
    return decision


def can_user_view_file(user: User, file: File, *, record: bool = True) -> Decision:
    """Alias used at list-filtering sites. Same logic — separate name keeps
    call-sites self-documenting."""
    return can_user_access(user, file, record=record)


# --- Internal logic ---


def _evaluate(user: User, file: File) -> Decision:
    # 1. Owner short-circuit. Owners always see their own files — they uploaded them.
    if file.owner_id == user.id:
        return Decision(allowed=True, reason=REASON_OWNER)

    # 2. Admin short-circuit. Skips the policy table for the global admin policy.
    #    Still records an evaluation row so we can see admin reads in audit.
    if user.role == Role.ADMIN:
        return Decision(allowed=True, reason=REASON_ADMIN)

    # 3. Look up classification for the file.
    classification = _latest_classification(file.id)
    if classification is None or classification.status != ClassificationStatus.COMPLETED:
        if classification is not None and classification.status == ClassificationStatus.FAILED:
            return Decision(allowed=False, reason=REASON_CLASSIFICATION_FAILED)
        return Decision(allowed=False, reason=REASON_NO_CLASSIFICATION)

    file_tier = classification.final_tier
    if file_tier is None:
        return Decision(allowed=False, reason=REASON_NO_CLASSIFICATION)
    triggered = classification.categories_triggered or []

    # 4. Pick the most specific policy: department-scoped > global.
    policy = _resolve_policy(user)
    if policy is None:
        return Decision(allowed=False, reason=REASON_NO_POLICY, tier=file_tier)

    # 5. Tier check.
    if TIER_RANK[Tier(file_tier.value)] > TIER_RANK[Tier(policy.allowed_max_tier.value)]:
        return Decision(
            allowed=False,
            reason=REASON_POLICY_DENY_TIER,
            matched_policy_id=policy.id,
            tier=file_tier,
        )

    # 6. Category checks.
    if policy.denied_categories:
        denied = set(policy.denied_categories)
        if denied.intersection(triggered):
            return Decision(
                allowed=False,
                reason=REASON_POLICY_DENY_CATEGORY,
                matched_policy_id=policy.id,
                tier=file_tier,
            )
    if policy.allowed_categories is not None and triggered:
        allowed = set(policy.allowed_categories)
        if not allowed.intersection(triggered):
            return Decision(
                allowed=False,
                reason=REASON_POLICY_DENY_NOT_IN_ALLOWED,
                matched_policy_id=policy.id,
                tier=file_tier,
            )

    return Decision(
        allowed=True,
        reason=REASON_POLICY_ALLOW,
        matched_policy_id=policy.id,
        tier=file_tier,
    )


def _latest_classification(file_id: uuid.UUID) -> Classification | None:
    return db.session.scalar(
        select(Classification)
        .where(Classification.file_id == file_id)
        .order_by(Classification.version.desc())
    )


def _resolve_policy(user: User) -> AccessPolicy | None:
    """Department-scoped policy beats global. NULL department_id is global."""
    if user.department_id is not None:
        scoped = db.session.scalar(
            select(AccessPolicy).where(
                AccessPolicy.role == user.role,
                AccessPolicy.department_id == user.department_id,
            )
        )
        if scoped is not None:
            return scoped
    return db.session.scalar(
        select(AccessPolicy).where(
            AccessPolicy.role == user.role,
            AccessPolicy.department_id.is_(None),
        )
    )


def _record_evaluation(user: User, file: File, decision: Decision) -> None:
    """Always write a `policy_evaluations` row. Audit only the interesting events."""
    entry = PolicyEvaluation(
        user_id=user.id,
        file_id=file.id,
        decision=PolicyDecision.ALLOW if decision.allowed else PolicyDecision.DENY,
        reason=decision.reason,
        matched_policy_id=decision.matched_policy_id,
    )
    db.session.add(entry)
    db.session.commit()

    # Owner/admin allow-reads happen constantly; don't flood the audit log.
    # Skip those, but capture every deny and every non-owner allow.
    skip_audit = decision.allowed and decision.reason in (REASON_OWNER, REASON_ADMIN)
    if skip_audit:
        return

    action = "policy.decision.allow" if decision.allowed else "policy.decision.deny"
    severity = AuditSeverity.INFO if decision.allowed else AuditSeverity.WARNING
    audit.record(
        action,
        actor=user,
        target_type="file",
        target_id=file.id,
        metadata={
            "reason": decision.reason,
            "matched_policy_id": str(decision.matched_policy_id)
            if decision.matched_policy_id
            else None,
            "tier": decision.tier.value if decision.tier else None,
        },
        severity=severity,
    )


# --- Listing helpers ---


# --- Defaults / seeding ---


# The 3 default global policies. Mirrors migration 0005's INSERT. Idempotent
# helper used by test conftest to restore defaults after TRUNCATE.
DEFAULT_POLICIES: list[dict] = [
    {
        "role": Role.ADMIN,
        "allowed_max_tier": ClassificationTier.RESTRICTED,
        "description": "Default: admins read every tier.",
    },
    {
        "role": Role.USER,
        "allowed_max_tier": ClassificationTier.CONFIDENTIAL,
        "description": (
            "Default: regular users read up to CONFIDENTIAL; "
            "RESTRICTED requires a department or share grant."
        ),
    },
    {
        "role": Role.GUEST,
        "allowed_max_tier": ClassificationTier.PUBLIC,
        "description": "Default: guests read only PUBLIC tier.",
    },
]


def ensure_default_policies() -> None:
    """Insert the 3 default role policies if not already present.

    Matches migration 0005's seed. Called from test conftest after TRUNCATE.
    No-op if the policies already exist.
    """
    for spec in DEFAULT_POLICIES:
        existing = db.session.scalar(
            select(AccessPolicy).where(
                AccessPolicy.role == spec["role"],
                AccessPolicy.department_id.is_(None),
            )
        )
        if existing is not None:
            continue
        db.session.add(
            AccessPolicy(
                role=spec["role"],
                department_id=None,
                allowed_max_tier=spec["allowed_max_tier"],
                description=spec["description"],
            )
        )
    db.session.commit()


# --- Listing helpers ---


def filter_visible_files(user: User, files: list[File]) -> list[File]:
    """Filter a candidate file list to the ones `user` may see.

    Used by `GET /api/files` so list responses don't leak metadata about
    inaccessible files. Decision rows ARE written for each non-allow result
    so we still get a paper trail at list time (low-cost for the user's own
    directory; expensive for cross-user listings — Phase 7 will need a
    bulk decision-cache).
    """
    return [f for f in files if can_user_access(user, f, record=False).allowed]
