"""files envelope encryption

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19

This migration adds the AES-GCM envelope-encryption columns to `files`.
Existing Phase-2 rows have no DEK and therefore can't be decrypted under
the new scheme, so we TRUNCATE the table first. Dev-only convenience;
production would require an explicit re-encryption backfill before
applying this migration.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase-2 rows lack a DEK; wipe them rather than carry undecryptable data.
    op.execute("TRUNCATE TABLE files CASCADE")

    op.add_column("files", sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False))
    op.add_column("files", sa.Column("nonce", sa.LargeBinary(), nullable=False))
    op.add_column("files", sa.Column("auth_tag", sa.LargeBinary(), nullable=False))
    op.add_column(
        "files",
        sa.Column("kek_version", sa.SmallInteger(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("files", "kek_version")
    op.drop_column("files", "auth_tag")
    op.drop_column("files", "nonce")
    op.drop_column("files", "wrapped_dek")
