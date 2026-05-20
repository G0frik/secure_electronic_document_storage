"""notifications

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-20

Phase 11 — in-app notification feed. We reuse `audit_log` as the
canonical event store (every notification references the audit row it
was triggered by) and add this table as the per-recipient feed projection.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("audit_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.String(length=512), nullable=True),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default="info",
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["audit_log_id"], ["audit_log.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_notifications_recipient_user_id",
        "notifications",
        ["recipient_user_id"],
    )
    op.create_index(
        "ix_notifications_created_at",
        "notifications",
        [sa.text("created_at DESC")],
    )
    # Hot path for the bell badge: "how many unread for this user?".
    op.execute(
        "CREATE INDEX ix_notifications_unread_recipient "
        "ON notifications (recipient_user_id, created_at DESC) "
        "WHERE read_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_notifications_unread_recipient")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index(
        "ix_notifications_recipient_user_id", table_name="notifications"
    )
    op.drop_table("notifications")
