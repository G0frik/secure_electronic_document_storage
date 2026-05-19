"""classifications

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    classification_status = postgresql.ENUM(
        "pending", "running", "completed", "failed", name="classification_status"
    )
    classification_tier = postgresql.ENUM(
        "public", "internal", "confidential", "restricted", name="classification_tier"
    )

    classification_status.create(op.get_bind(), checkfirst=True)
    classification_tier.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "completed",
                "failed",
                name="classification_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "final_tier",
            postgresql.ENUM(
                "public",
                "internal",
                "confidential",
                "restricted",
                name="classification_tier",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "zero_shot_tier",
            postgresql.ENUM(
                "public",
                "internal",
                "confidential",
                "restricted",
                name="classification_tier",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "presidio_tier",
            postgresql.ENUM(
                "public",
                "internal",
                "confidential",
                "restricted",
                name="classification_tier",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("raw_scores", postgresql.JSONB(), nullable=True),
        sa.Column("categories_triggered", postgresql.JSONB(), nullable=True),
        sa.Column("presidio_entities", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("classifier_version", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "version", name="uq_classifications_file_version"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_classifications_file_id", "classifications", ["file_id"])
    op.create_index("ix_classifications_status", "classifications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_classifications_status", table_name="classifications")
    op.drop_index("ix_classifications_file_id", table_name="classifications")
    op.drop_table("classifications")
    op.execute("DROP TYPE IF EXISTS classification_tier")
    op.execute("DROP TYPE IF EXISTS classification_status")
