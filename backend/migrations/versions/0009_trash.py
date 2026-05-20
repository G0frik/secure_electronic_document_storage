"""files.deleted_at + folders.deleted_at

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-20

Phase 9 — soft-delete (trash). Adds a nullable `deleted_at` timestamp to
`files` and `folders`. Listings filter out rows where it is set; a Celery
task hard-deletes files trashed more than 30 days ago.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_files_deleted_at",
        "files",
        ["deleted_at"],
        # Index only trashed rows so the reaper sweep is O(trash size).
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )

    op.add_column(
        "folders",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_folders_deleted_at",
        "folders",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_folders_deleted_at", table_name="folders")
    op.drop_column("folders", "deleted_at")
    op.drop_index("ix_files_deleted_at", table_name="files")
    op.drop_column("files", "deleted_at")
