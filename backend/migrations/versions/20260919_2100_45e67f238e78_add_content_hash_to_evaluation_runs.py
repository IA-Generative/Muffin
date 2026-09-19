"""Add content_hash to evaluation_runs for deduplication.

Revision ID: 45e67f238e78
Revises: 49defa648bf4
Create Date: 2026-09-19 21:00:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "45e67f238e78"
down_revision = "49defa648bf4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_evaluation_runs_collection_hash",
        "evaluation_runs",
        ["collection_id", "content_hash", "llm_model"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_evaluation_runs_collection_hash",
        table_name="evaluation_runs",
    )
    op.drop_column("evaluation_runs", "content_hash")
