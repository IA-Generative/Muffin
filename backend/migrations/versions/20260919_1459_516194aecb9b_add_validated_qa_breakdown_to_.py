"""add validated qa breakdown to evaluation runs

Revision ID: 516194aecb9b
Revises: 99551a95a5dc
Create Date: 2026-09-19 14:59:03.040117

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "516194aecb9b"
down_revision: str | Sequence[str] | None = "99551a95a5dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # No server_default needed anywhere here: evaluation_runs/evaluation_results have never had a
    # write path until this feature (see app/models/evaluation.py), so they're empty in every
    # real deployment.
    op.add_column("evaluation_results", sa.Column("validated", sa.Boolean(), nullable=False))
    op.add_column("evaluation_runs", sa.Column("validated_pair_count", sa.Integer(), nullable=False))
    op.add_column("evaluation_runs", sa.Column("validated_precision_at_k", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("validated_recall_at_k", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("validated_mrr", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("validated_ndcg", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("unvalidated_pair_count", sa.Integer(), nullable=False))
    op.add_column("evaluation_runs", sa.Column("unvalidated_precision_at_k", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("unvalidated_recall_at_k", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("unvalidated_mrr", sa.Float(), nullable=True))
    op.add_column("evaluation_runs", sa.Column("unvalidated_ndcg", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("evaluation_runs", "unvalidated_ndcg")
    op.drop_column("evaluation_runs", "unvalidated_mrr")
    op.drop_column("evaluation_runs", "unvalidated_recall_at_k")
    op.drop_column("evaluation_runs", "unvalidated_precision_at_k")
    op.drop_column("evaluation_runs", "unvalidated_pair_count")
    op.drop_column("evaluation_runs", "validated_ndcg")
    op.drop_column("evaluation_runs", "validated_mrr")
    op.drop_column("evaluation_runs", "validated_recall_at_k")
    op.drop_column("evaluation_runs", "validated_precision_at_k")
    op.drop_column("evaluation_runs", "validated_pair_count")
    op.drop_column("evaluation_results", "validated")
