"""playground_rows.llm_output: the LLM's raw answer and reasoning, encrypted

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-28

Envelope-encrypted like the playground documents (base64 fields in one JSONB value),
because a model's reasoning often quotes the document.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("playground_rows", sa.Column("llm_output", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("playground_rows", "llm_output")
