"""file_versions table + files.current_version counter

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-21

Phase 15 — file versioning. The current version of every file continues to
live in the `files` row (so existing code paths keep working). Historical
snapshots go into `file_versions`. A counter `files.current_version`
identifies the current version number (starts at 1; bumps on every new
upload).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- files.current_version counter ---
    op.add_column(
        "files",
        sa.Column(
            "current_version",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
    )

    # --- file_versions table ---
    op.create_table(
        "file_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.SmallInteger(), nullable=False),
        # MinIO key for this version's ciphertext blob (unique per version).
        sa.Column(
            "storage_key",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
        ),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        # Envelope encryption blob — same layout as files
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("auth_tag", sa.LargeBinary(), nullable=False),
        sa.Column(
            "kek_version",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "file_id",
            "version_number",
            name="uq_file_versions_file_id_version_number",
        ),
    )
    op.create_index("ix_file_versions_file_id", "file_versions", ["file_id"])
    op.create_index(
        "ix_file_versions_uploaded_at", "file_versions", ["uploaded_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_file_versions_uploaded_at", table_name="file_versions")
    op.drop_index("ix_file_versions_file_id", table_name="file_versions")
    op.drop_table("file_versions")
    op.drop_column("files", "current_version")
