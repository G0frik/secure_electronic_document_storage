"""tags + file_tags + tier_override_requests

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-20

Phase 10 — user tags + human-in-the-loop tier override workflow. Tag
names are normalised on write (trim + lowercase) so the UNIQUE on
`tags.name` doubles as a dedup index.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- tags ---
    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )

    # --- file_tags (M2M join) ---
    op.create_table(
        "file_tags",
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("applied_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("file_id", "tag_id"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["applied_by_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_file_tags_tag_id", "file_tags", ["tag_id"])

    # --- tier_override_requests ---
    override_status = postgresql.ENUM(
        "pending", "approved", "denied", name="tier_override_status"
    )
    override_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tier_override_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "classification_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "requested_by_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "current_tier",
            postgresql.ENUM(
                "public",
                "internal",
                "confidential",
                "restricted",
                name="classification_tier",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "requested_tier",
            postgresql.ENUM(
                "public",
                "internal",
                "confidential",
                "restricted",
                name="classification_tier",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "approved",
                "denied",
                name="tier_override_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["classification_id"], ["classifications.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_tier_override_requests_file_id",
        "tier_override_requests",
        ["file_id"],
    )
    op.create_index(
        "ix_tier_override_requests_status",
        "tier_override_requests",
        ["status"],
    )
    # At most one *pending* request per file at a time. Historical
    # approved/denied rows are not constrained — they accumulate as audit.
    op.execute(
        "CREATE UNIQUE INDEX ix_tier_override_requests_one_pending_per_file "
        "ON tier_override_requests (file_id) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_tier_override_requests_one_pending_per_file"
    )
    op.drop_index(
        "ix_tier_override_requests_status", table_name="tier_override_requests"
    )
    op.drop_index(
        "ix_tier_override_requests_file_id", table_name="tier_override_requests"
    )
    op.drop_table("tier_override_requests")
    op.execute("DROP TYPE IF EXISTS tier_override_status")

    op.drop_index("ix_file_tags_tag_id", table_name="file_tags")
    op.drop_table("file_tags")
    op.drop_table("tags")
