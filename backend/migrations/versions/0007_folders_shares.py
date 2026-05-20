"""folders + files.folder_id + shares

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-20

Phase 7 — internal sharing with folder inheritance. Folders are pure
metadata (MinIO has no folders); shares are polymorphic over file|folder
and propagate access cloud-drive style.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- folders ---
    op.create_table(
        "folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_folders_owner_id", "folders", ["owner_id"])
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"])

    # Unique folder name per (owner, parent). Postgres 15+ NULLS NOT DISTINCT
    # treats NULL parent_id (root folders) as the same value, so two root
    # folders with the same name conflict — same intent as a regular UNIQUE.
    op.execute(
        "ALTER TABLE folders ADD CONSTRAINT uq_folders_owner_parent_name "
        "UNIQUE NULLS NOT DISTINCT (owner_id, parent_id, name)"
    )

    # --- files.folder_id ---
    op.add_column(
        "files",
        sa.Column(
            "folder_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_files_folder_id",
        "files",
        "folders",
        ["folder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_files_folder_id", "files", ["folder_id"])

    # --- shares ---
    share_target_type = postgresql.ENUM("file", "folder", name="share_target_type")
    share_permission = postgresql.ENUM("viewer", "editor", name="share_permission")
    share_target_type.create(op.get_bind(), checkfirst=True)
    share_permission.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "target_type",
            postgresql.ENUM(
                "file", "folder", name="share_target_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "permission",
            postgresql.ENUM(
                "viewer", "editor", name="share_permission", create_type=False
            ),
            nullable=False,
            server_default="viewer",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["granter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "granter_id <> recipient_id", name="ck_shares_granter_ne_recipient"
        ),
    )

    op.create_index("ix_shares_granter_id", "shares", ["granter_id"])
    op.create_index("ix_shares_recipient_id", "shares", ["recipient_id"])
    op.create_index("ix_shares_target", "shares", ["target_type", "target_id"])
    # One active (non-revoked) share per (target, recipient). Historic revoked
    # rows are allowed.
    op.execute(
        "CREATE UNIQUE INDEX ix_shares_unique_active "
        "ON shares (target_type, target_id, recipient_id) "
        "WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_shares_unique_active")
    op.drop_index("ix_shares_target", table_name="shares")
    op.drop_index("ix_shares_recipient_id", table_name="shares")
    op.drop_index("ix_shares_granter_id", table_name="shares")
    op.drop_table("shares")
    op.execute("DROP TYPE IF EXISTS share_permission")
    op.execute("DROP TYPE IF EXISTS share_target_type")

    op.drop_index("ix_files_folder_id", table_name="files")
    op.drop_constraint("fk_files_folder_id", "files", type_="foreignkey")
    op.drop_column("files", "folder_id")

    op.execute("ALTER TABLE folders DROP CONSTRAINT IF EXISTS uq_folders_owner_parent_name")
    op.drop_index("ix_folders_parent_id", table_name="folders")
    op.drop_index("ix_folders_owner_id", table_name="folders")
    op.drop_table("folders")
