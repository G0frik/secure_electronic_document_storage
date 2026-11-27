"""playground_runs / _documents / _rows / _setups: the admin classifier playground

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-27

Runs, their encrypted input/attacked documents, one row per classifier setup, and named
setups. Used only when the stack runs with PLAYGROUND=1; the tables stay empty otherwise.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "playground_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("input_kind", sa.String(16), nullable=False),
        sa.Column("input_ref", sa.String(512), nullable=True),
        sa.Column("attack", postgresql.JSONB(), nullable=False),
        sa.Column("attack_source", sa.String(32), nullable=False),
        sa.Column("explain", sa.Boolean(), nullable=False),
        sa.Column("preset", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_index("ix_playground_runs_created_at", "playground_runs", ["created_at"])
    op.create_table(
        "playground_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playground_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(128), nullable=False, unique=True),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("auth_tag", sa.LargeBinary(), nullable=False),
        sa.Column("kek_version", sa.SmallInteger(), nullable=False),
    )
    op.create_index("ix_playground_documents_run_id", "playground_documents", ["run_id"])
    op.create_table(
        "playground_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playground_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("setup", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("explanation", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_playground_rows_run_id", "playground_rows", ["run_id"])
    op.create_table(
        "playground_setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("playground_setups")
    op.drop_index("ix_playground_rows_run_id", table_name="playground_rows")
    op.drop_table("playground_rows")
    op.drop_index("ix_playground_documents_run_id", table_name="playground_documents")
    op.drop_table("playground_documents")
    op.drop_index("ix_playground_runs_created_at", table_name="playground_runs")
    op.drop_table("playground_runs")
