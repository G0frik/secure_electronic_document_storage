"""users.quota_bytes + users.used_bytes

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-20

Phase 12 — per-user storage quota. `quota_bytes` is the cap, `used_bytes`
is a denormalised running total that the upload + hard-delete paths
maintain; a Celery task recomputes it nightly as a drift safety net.

Default cap: 2 GiB. Backfill `used_bytes` from `SUM(files.size_bytes)`
on upgrade so existing users see an honest number from the first request.
Trashed files count toward quota (matches Google Drive / Dropbox); only
hard-delete decrements.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "quota_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=str(_DEFAULT_QUOTA_BYTES),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "used_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )

    # Backfill the denormalised counter for any rows that pre-date Phase 12.
    # Trashed files count too — the column was added in Phase 9 and `files`
    # still holds the row.
    op.execute(
        """
        UPDATE users u
           SET used_bytes = COALESCE((
               SELECT SUM(f.size_bytes) FROM files f WHERE f.owner_id = u.id
           ), 0)
        """
    )


def downgrade() -> None:
    op.drop_column("users", "used_bytes")
    op.drop_column("users", "quota_bytes")
