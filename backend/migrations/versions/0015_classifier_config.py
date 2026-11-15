"""classifications.classifier_config: engine, model, prompt and defenses per result

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-15

The semantic layer can now be an NLI model or an LLM, with optional
prompt-injection defenses. Each classification row records which setup
produced it (and whether the injection detector asked for a review).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "classifications",
        sa.Column("classifier_config", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classifications", "classifier_config")
