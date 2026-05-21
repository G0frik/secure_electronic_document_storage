"""Phase 16 — `flask seed-demo` smoke tests.

The demo seed is meant to be run repeatedly without polluting the DB.
These tests verify:
  * First run creates users (via seed-dev path) + files + folders + shares
  * Second run is a no-op — every counter returns 0
  * The synchronously-classified file ends up COMPLETED so the pending
    override is creatable in the same run
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.cli import DEV_DEPARTMENTS, DEV_USERS
from app.config import settings
from app.models.classification import Classification, ClassificationStatus
from app.models.file import File
from app.models.folder import Folder
from app.models.share import Share
from app.models.share_link import ShareLink
from app.models.tier_override import OverrideStatus, TierOverrideRequest
from app.models.user import Department
from app.services import demo_seed, users


def _seed_users_inline(db_session) -> None:
    """Mirror what `flask seed-dev` does, without going through Click — the
    demo-seed under test depends on those users existing.
    """
    for name in DEV_DEPARTMENTS:
        if db_session.query(Department).filter_by(name=name).first() is None:
            db_session.add(Department(name=name))
    db_session.commit()

    original_hibp = settings.hibp_enabled
    settings.hibp_enabled = False
    try:
        for spec in DEV_USERS:
            if users.get_user_by_email(spec.email) is not None:
                continue
            dept_id = None
            if spec.department is not None:
                dept = (
                    db_session.query(Department).filter_by(name=spec.department).first()
                )
                dept_id = dept.id if dept else None
            users.create_user(
                email=spec.email,
                password=spec.password,
                role=spec.role,
                department_id=dept_id,
                is_manager=spec.is_manager,
            )
    finally:
        settings.hibp_enabled = original_hibp


def test_demo_seed_creates_expected_state(app, db_session) -> None:
    """First invocation should create files + folders + shares + link + override."""
    with app.app_context():
        _seed_users_inline(db_session)

        counts = demo_seed.run_demo_seed(quiet=True)

        # Numbers from the spec table in demo_seed._DEMO_FILES:
        # 7 files, 2 folders (Press, HR), 2 shares, 1 link, 1 override.
        assert counts["files_created"] == 7
        assert counts["folders_created"] == 2
        assert counts["shares_created"] == 2
        assert counts["links_created"] == 1
        assert counts["overrides_created"] == 1

        # DB invariants
        assert db_session.scalar(select(Folder).where(Folder.name == "HR")) is not None
        assert (
            db_session.scalar(select(Folder).where(Folder.name == "Press")) is not None
        )

        # The override target was classified synchronously so the override
        # was creatable in this same run.
        strategy = db_session.scalar(
            select(File).where(
                File.original_filename == "06_confidential_product_strategy.txt"
            )
        )
        assert strategy is not None
        completed = db_session.scalar(
            select(Classification).where(
                Classification.file_id == strategy.id,
                Classification.status == ClassificationStatus.COMPLETED,
            )
        )
        assert completed is not None

        override = db_session.scalar(
            select(TierOverrideRequest).where(
                TierOverrideRequest.file_id == strategy.id,
                TierOverrideRequest.status == OverrideStatus.PENDING,
            )
        )
        assert override is not None

        # The link was minted on the same strategy file.
        link = db_session.scalar(
            select(ShareLink).where(
                ShareLink.file_id == strategy.id,
                ShareLink.revoked_at.is_(None),
            )
        )
        assert link is not None


def test_demo_seed_is_idempotent(app, db_session) -> None:
    """Second invocation should be a complete no-op."""
    with app.app_context():
        _seed_users_inline(db_session)

        demo_seed.run_demo_seed(quiet=True)
        # Snapshot the world after run 1.
        files_before = db_session.scalar(
            select(func.count()).select_from(File)
        )
        shares_before = db_session.scalar(
            select(func.count()).select_from(Share)
        )

        counts2 = demo_seed.run_demo_seed(quiet=True)

        assert all(v == 0 for v in counts2.values()), counts2

        files_after = db_session.scalar(
            select(func.count()).select_from(File)
        )
        shares_after = db_session.scalar(
            select(func.count()).select_from(Share)
        )
        assert files_after == files_before
        assert shares_after == shares_before


def test_demo_seed_errors_without_users(app, db_session) -> None:
    """Calling the demo seeder before `seed-dev` should fail with a clear
    ClickException pointing the user at the prerequisite.
    """
    import click

    with app.app_context():
        # No users exist (autouse `_isolate_state` truncated everything).
        # The demo seeder should bail loudly rather than silently skipping.
        try:
            demo_seed.run_demo_seed(quiet=True)
        except click.ClickException as exc:
            assert "seed-dev" in exc.message
            return
        raise AssertionError("Expected ClickException; demo seed should refuse to run.")
