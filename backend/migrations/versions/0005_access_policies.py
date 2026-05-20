"""access_policies + policy_evaluations + default policy seed

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-20

Phase 5 — tier-based RBAC. Creates the two policy tables, defines the
`policy_decision` enum, and seeds the three default global policies
(admin / user / guest).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum ---
    policy_decision = postgresql.ENUM("allow", "deny", name="policy_decision")
    policy_decision.create(op.get_bind(), checkfirst=True)

    # --- access_policies ---
    op.create_table(
        "access_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("admin", "user", "guest", name="role", create_type=False),
            nullable=False,
        ),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "allowed_max_tier",
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
        sa.Column("allowed_categories", postgresql.JSONB(), nullable=True),
        sa.Column("denied_categories", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_access_policies_role", "access_policies", ["role"])
    op.create_index(
        "ix_access_policies_department_id", "access_policies", ["department_id"]
    )

    # --- policy_evaluations ---
    op.create_table(
        "policy_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "decision",
            postgresql.ENUM("allow", "deny", name="policy_decision", create_type=False),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("matched_policy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["matched_policy_id"], ["access_policies.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_policy_evaluations_user_id", "policy_evaluations", ["user_id"]
    )
    op.create_index(
        "ix_policy_evaluations_file_id", "policy_evaluations", ["file_id"]
    )
    op.create_index(
        "ix_policy_evaluations_evaluated_at",
        "policy_evaluations",
        [sa.text("evaluated_at DESC")],
    )

    # --- Seed: 3 default global policies (department_id NULL) ---
    op.execute(
        """
        INSERT INTO access_policies (id, role, allowed_max_tier, description)
        VALUES
          (gen_random_uuid(), 'admin', 'restricted',
           'Default: admins read every tier.'),
          (gen_random_uuid(), 'user', 'confidential',
           'Default: regular users read up to CONFIDENTIAL; RESTRICTED requires a department or share grant.'),
          (gen_random_uuid(), 'guest', 'public',
           'Default: guests read only PUBLIC tier.')
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_policy_evaluations_evaluated_at", table_name="policy_evaluations"
    )
    op.drop_index("ix_policy_evaluations_file_id", table_name="policy_evaluations")
    op.drop_index("ix_policy_evaluations_user_id", table_name="policy_evaluations")
    op.drop_table("policy_evaluations")

    op.drop_index("ix_access_policies_department_id", table_name="access_policies")
    op.drop_index("ix_access_policies_role", table_name="access_policies")
    op.drop_table("access_policies")

    op.execute("DROP TYPE IF EXISTS policy_decision")
