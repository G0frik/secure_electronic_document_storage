"""Phase 16 — Demo seed.

A richer counterpart to `seed-dev`: on top of the 5 users + 3 departments,
this seeds a believable demo state:

  * Uploads sample files from `classify_sensitivity_data/data/test_corpus/`
    on behalf of alice, bob, and admin (one file per tier where possible)
  * Creates a couple of folders and drops files into them
  * Sets up internal shares (alice → bob, admin → guest)
  * Mints an external magic link
  * Files a pending tier-override request

Idempotency: each step checks "does this already exist?" before creating.
Re-running is a no-op if the demo state is already present.

The classifier is left to run via the live Celery worker — the script
returns immediately after enqueueing. For one specific file (the
override target) we also drive a synchronous classification so the
override request is creatable in the same run; without this the pending
request creation would 409 with `classification_pending`.
"""

from __future__ import annotations

import io
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import click
from sqlalchemy import select
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.logging_config import get_logger
from app.models.classification import ClassificationStatus, ClassificationTier
from app.models.file import File
from app.models.folder import Folder
from app.models.share import Share, SharePermission, ShareTargetType
from app.models.share_link import ShareLink
from app.models.tier_override import OverrideStatus, TierOverrideRequest
from app.models.user import User
from app.services import (
    classification,
    files,
    folders,
    share_links,
    shares,
    tier_overrides,
    users,
)

log = get_logger(__name__)


# Resolve `classify_sensitivity_data/data/test_corpus/` regardless of where
# the CLI is run from. In the docker container it's `/app/...` because the
# backend container only sees its own subtree; we ALSO support running
# from the project root for local invocation.
_CORPUS_CANDIDATES = [
    Path("/app/classify_sensitivity_data/data/test_corpus"),
    Path(__file__).resolve().parents[3] / "classify_sensitivity_data/data/test_corpus",
]


@dataclass(frozen=True)
class _DemoFile:
    """Spec for one file we want to seed."""

    owner_email: str
    corpus_filename: str
    folder: str | None = None
    # Set True for the single file we want to drive synchronously so the
    # tier-override workflow can hit it on the same seed run.
    classify_synchronously: bool = False


# Tiered selection from the test corpus — one example per tier per owner
# where the corpus supports it. Folder placement mirrors a realistic org:
# HR records under an "HR" folder for bob, salary review private, etc.
_DEMO_FILES: list[_DemoFile] = [
    # Alice (marketing) — public + internal + confidential
    _DemoFile(
        owner_email="alice@example.com",
        corpus_filename="01_public_press_release.txt",
        folder="Press",
    ),
    _DemoFile(
        owner_email="alice@example.com",
        corpus_filename="03_internal_office_memo.txt",
    ),
    _DemoFile(
        owner_email="alice@example.com",
        corpus_filename="06_confidential_product_strategy.txt",
        # This is the one we'll drive synchronously so the override request
        # can be filed on it within the same seed run.
        classify_synchronously=True,
    ),
    # Bob (hr) — sensitive HR records belong to him
    _DemoFile(
        owner_email="bob@example.com",
        corpus_filename="05_confidential_salary_review.txt",
        folder="HR",
    ),
    _DemoFile(
        owner_email="bob@example.com",
        corpus_filename="07_restricted_hr_records.txt",
        folder="HR",
    ),
    # Admin — security creds (RESTRICTED, can't have an external link)
    _DemoFile(
        owner_email="admin@example.com",
        corpus_filename="08_restricted_security_credentials.txt",
    ),
    _DemoFile(
        owner_email="admin@example.com",
        corpus_filename="09_public_announcement_uk.txt",
    ),
]


def _find_corpus() -> Path | None:
    """Locate the test corpus dir on disk. Returns None if missing — the
    demo will fall back to synthetic placeholder content so the script
    still works end-to-end without the corpus.
    """
    for candidate in _CORPUS_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def _get_user(email: str) -> User:
    """Lookup helper that errors loudly if a seeded user is missing."""
    user = users.get_user_by_email(email)
    if user is None:
        raise click.ClickException(
            f"User {email!r} not found. Run `flask seed-dev` first."
        )
    return user


def _existing_file(owner: User, filename: str) -> File | None:
    return db.session.scalar(
        select(File).where(
            File.owner_id == owner.id,
            File.original_filename == filename,
            File.deleted_at.is_(None),
        )
    )


def _existing_folder(owner: User, name: str) -> Folder | None:
    return db.session.scalar(
        select(Folder).where(
            Folder.owner_id == owner.id,
            Folder.name == name,
            Folder.parent_id.is_(None),
        )
    )


def _ensure_folder(owner: User, name: str) -> Folder:
    existing = _existing_folder(owner, name)
    if existing is not None:
        return existing
    return folders.create_folder(owner=owner, name=name)


def _ensure_file(spec: _DemoFile, corpus_dir: Path | None) -> tuple[File, bool]:
    """Upload the file if it doesn't already exist. Returns (file, created)."""
    owner = _get_user(spec.owner_email)
    existing = _existing_file(owner, spec.corpus_filename)
    if existing is not None:
        return existing, False

    if corpus_dir is not None and (corpus_dir / spec.corpus_filename).is_file():
        body = (corpus_dir / spec.corpus_filename).read_bytes()
    else:
        # Synthetic fallback so the script works without the corpus dir.
        # Content is still classifier-meaningful so tiering still works.
        body = (
            f"[demo placeholder for {spec.corpus_filename}]\n"
            "This is internal corporate content.\n"
        ).encode()

    folder_id: uuid.UUID | None = None
    if spec.folder:
        folder_id = _ensure_folder(owner, spec.folder).id

    storage = FileStorage(
        stream=io.BytesIO(body),
        filename=spec.corpus_filename,
        content_type="text/plain",
    )
    record = files.create_from_upload(
        owner=owner,
        uploaded=storage,
        folder_id=folder_id,
    )

    # Drive the classifier synchronously for the override target — the
    # override service rejects requests on un-classified files.
    if spec.classify_synchronously:
        try:
            classification.run_classification(record.id)
        except Exception as exc:  # noqa: BLE001 — demo only, log + continue
            log.warning(
                "demo_seed.synchronous_classification_failed",
                file_id=str(record.id),
                error=str(exc),
            )

    return record, True


def _ensure_share(
    *,
    granter: User,
    target_type: ShareTargetType,
    target_id: uuid.UUID,
    recipient_email: str,
    permission: SharePermission = SharePermission.VIEWER,
) -> tuple[Share | None, bool]:
    """Returns (share, created). Skips silently if the share already exists."""
    existing = db.session.scalar(
        select(Share).where(
            Share.target_type == target_type,
            Share.target_id == target_id,
            Share.recipient_id
            == _get_user(recipient_email).id,
            Share.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return existing, False
    try:
        share = shares.create_share(
            granter=granter,
            target_type=target_type,
            target_id=target_id,
            recipient_email=recipient_email,
            permission=permission,
        )
        return share, True
    except shares.ShareAlreadyExistsError:
        return None, False


def _ensure_active_share_link(
    *, creator: User, file_record: File
) -> tuple[str | None, bool]:
    """Mint a new active share-link if none exist on the file. Returns
    (raw_token, created). Returns (None, False) if already present.
    """
    existing = db.session.scalar(
        select(ShareLink).where(
            ShareLink.file_id == file_record.id,
            ShareLink.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return None, False

    # Classifier may not have completed yet; the link API rejects pending
    # files. For demo simplicity we skip silently in that case.
    current = classification.get_latest(file_record.id)
    if current is None or current.status != ClassificationStatus.COMPLETED:
        return None, False
    if current.final_tier == ClassificationTier.RESTRICTED:
        return None, False

    minted = share_links.create_link(creator=creator, file_id=file_record.id)
    return minted.token, True


def _ensure_pending_override(
    *, owner: User, file_record: File, requested_tier: ClassificationTier
) -> tuple[TierOverrideRequest | None, bool]:
    """File a pending tier-override request. Skips if one is already pending."""
    existing = db.session.scalar(
        select(TierOverrideRequest).where(
            TierOverrideRequest.file_id == file_record.id,
            TierOverrideRequest.status == OverrideStatus.PENDING,
        )
    )
    if existing is not None:
        return existing, False

    current = classification.get_latest(file_record.id)
    if current is None or current.status != ClassificationStatus.COMPLETED:
        return None, False
    if current.final_tier == requested_tier:
        return None, False

    try:
        request = tier_overrides.create_request(
            file=file_record,
            requested_tier=requested_tier,
            justification=(
                "Demo seed: marketing wants this strategy doc reclassified "
                "as INTERNAL ahead of the team announcement."
            ),
            actor=owner,
        )
        return request, True
    except tier_overrides.SameTierError:
        return None, False


def run_demo_seed(*, quiet: bool = False) -> dict[str, int]:
    """Idempotent demo seeder. Returns counts of items created."""
    counts = {
        "files_created": 0,
        "folders_created": 0,
        "shares_created": 0,
        "links_created": 0,
        "overrides_created": 0,
    }

    corpus_dir = _find_corpus()
    if corpus_dir is None and not quiet:
        click.echo(
            "WARN: test corpus directory not found; "
            "uploading synthetic placeholders instead.",
            err=True,
        )

    # 1. Pre-create folders so the file-create step doesn't repeat the lookup.
    pre_existing_folders = set(
        db.session.scalars(select(Folder.id)).all()
    )

    # 2. Upload files.
    created_files: dict[str, File] = {}
    for spec in _DEMO_FILES:
        record, created = _ensure_file(spec, corpus_dir)
        created_files[spec.corpus_filename] = record
        if created:
            counts["files_created"] += 1

    # Recount the folders that ended up freshly created.
    final_folders = set(db.session.scalars(select(Folder.id)).all())
    counts["folders_created"] = len(final_folders - pre_existing_folders)

    # 3. Internal share: alice's PUBLIC press release with bob.
    alice = _get_user("alice@example.com")
    press_release = created_files.get("01_public_press_release.txt")
    if press_release is not None:
        _, created = _ensure_share(
            granter=alice,
            target_type=ShareTargetType.FILE,
            target_id=press_release.id,
            recipient_email="bob@example.com",
        )
        if created:
            counts["shares_created"] += 1

    # 4. Folder share: bob's HR folder shared with admin.
    bob = _get_user("bob@example.com")
    hr_folder = _existing_folder(bob, "HR")
    if hr_folder is not None:
        _, created = _ensure_share(
            granter=bob,
            target_type=ShareTargetType.FOLDER,
            target_id=hr_folder.id,
            recipient_email="admin@example.com",
        )
        if created:
            counts["shares_created"] += 1

    # 5. External share-link on the (classified) strategy doc.
    strategy = created_files.get("06_confidential_product_strategy.txt")
    minted_token: str | None = None
    if strategy is not None:
        token, created = _ensure_active_share_link(
            creator=alice, file_record=strategy
        )
        if created:
            counts["links_created"] += 1
            minted_token = token

    # 6. Pending tier-override request on the strategy doc.
    if strategy is not None:
        _, created = _ensure_pending_override(
            owner=alice,
            file_record=strategy,
            requested_tier=ClassificationTier.INTERNAL,
        )
        if created:
            counts["overrides_created"] += 1

    db.session.commit()

    if not quiet:
        _print_summary(counts, minted_token)

    return counts


def _print_summary(counts: dict[str, int], minted_token: str | None) -> None:
    click.echo("")
    click.echo("=" * 72)
    click.echo("  Phase 16 demo seed — summary")
    click.echo("=" * 72)
    for key, value in counts.items():
        click.echo(f"  {key:<24} {value}")
    click.echo("")
    if minted_token is not None:
        click.echo("Fresh external share-link minted:")
        click.echo(f"  http://localhost:5173/share/{minted_token}")
        click.echo("(opens the public landing page — no auth needed)")
    click.echo("")
    click.echo("Demo accounts (passwords seeded by `flask seed-dev`):")
    click.echo("  admin@example.com / ChangeMeNow123!")
    click.echo("  alice@example.com / AlicePassword123!    (marketing, user)")
    click.echo("  bob@example.com   / BobPassword123!      (hr, manager)")
    click.echo("  carol@example.com / CarolPassword123!    (engineering, user)")
    click.echo("  dave@example.com  / DavePassword123!     (no dept, guest)")
    click.echo("=" * 72)


# Hooked into Flask CLI in app/cli.py
def seed_demo_cli(quiet: bool = False) -> None:  # noqa: D401
    """Entrypoint for `flask seed-demo`."""
    try:
        run_demo_seed(quiet=quiet)
    except click.ClickException:
        raise
    except Exception as exc:
        click.echo(f"Demo seed failed: {exc}", err=True)
        sys.exit(1)
