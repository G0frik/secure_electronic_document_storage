"""groups + user_groups + access_policies.group_id + users.session_invalid_before

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-21

Phase 13 — admin panel. Adds the `groups` M2M layer (so policies can
target group membership in addition to roles + departments) plus the
`session_invalid_before` timestamp that the admin "force logout" action
bumps to invalidate all live sessions for a user.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- groups ---
    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_groups_name"),
    )

    # --- user_groups (M2M) ---
    op.create_table(
        "user_groups",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("added_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])

    # --- access_policies.group_id ---
    op.add_column(
        "access_policies",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_access_policies_group_id",
        "access_policies",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_access_policies_group_id", "access_policies", ["group_id"])

    # --- users.session_invalid_before ---
    op.add_column(
        "users",
        sa.Column(
            "session_invalid_before",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "session_invalid_before")

    op.drop_index("ix_access_policies_group_id", table_name="access_policies")
    op.drop_constraint(
        "fk_access_policies_group_id", "access_policies", type_="foreignkey"
    )
    op.drop_column("access_policies", "group_id")

    op.drop_index("ix_user_groups_group_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_table("groups")
