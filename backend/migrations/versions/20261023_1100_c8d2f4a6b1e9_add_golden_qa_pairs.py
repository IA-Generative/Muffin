"""add golden QA pairs and their evaluation breakdown

Revision ID: c8d2f4a6b1e9
Revises: b7c4e1d9a2f3
Create Date: 2026-10-23 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c8d2f4a6b1e9"
down_revision: str | Sequence[str] | None = "b7c4e1d9a2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GLOBAL_METRICS = ("precision_at_k", "recall_at_k", "mrr", "ndcg")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("qa_pairs", sa.Column("golden", sa.Boolean(), server_default="false", nullable=False))
    op.add_column(
        "qa_pairs", sa.Column("relevant_document_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("evaluation_results", sa.Column("golden", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("evaluation_runs", sa.Column("golden_pair_count", sa.Integer(), server_default="0", nullable=False))
    for metric in _GLOBAL_METRICS:
        op.add_column("evaluation_runs", sa.Column(f"golden_{metric}", sa.Float(), nullable=True))
        # A run with only golden pairs has no global aggregate left to report.
        op.alter_column("evaluation_runs", metric, existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Runs that only had golden pairs have no global aggregate: they cannot satisfy NOT NULL again.
    op.execute("DELETE FROM evaluation_runs WHERE precision_at_k IS NULL")
    for metric in _GLOBAL_METRICS:
        op.alter_column("evaluation_runs", metric, existing_type=sa.Float(), nullable=False)
        op.drop_column("evaluation_runs", f"golden_{metric}")
    op.drop_column("evaluation_runs", "golden_pair_count")
    op.drop_column("evaluation_results", "golden")
    op.drop_column("qa_pairs", "relevant_document_ids")
    op.drop_column("qa_pairs", "golden")
