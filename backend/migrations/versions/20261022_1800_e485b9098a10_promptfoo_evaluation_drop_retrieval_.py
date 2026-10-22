"""promptfoo evaluation: drop retrieval metric columns, store artifacts in RustFS

The evaluation engine becomes promptfoo (see docs/promptfoo-evaluation-plan.md):
scores are no longer stored per column, the run's results.json / report.html
artifacts in RustFS are the source of truth, read back at display time.

Revision ID: e485b9098a10
Revises: d7f1b5a9c3e6
Create Date: 2026-10-22 18:00:20.130481

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e485b9098a10"
down_revision: str | Sequence[str] | None = "d7f1b5a9c3e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The four retrieval metrics, each stored globally plus per golden/validated/
# unvalidated subset - all replaced by promptfoo's factuality, read from the
# run's results.json artifact at display time.
_METRIC_COLUMNS = [
    "precision_at_k",
    "recall_at_k",
    "mrr",
    "ndcg",
    "golden_precision_at_k",
    "golden_recall_at_k",
    "golden_mrr",
    "golden_ndcg",
    "validated_precision_at_k",
    "validated_recall_at_k",
    "validated_mrr",
    "validated_ndcg",
    "unvalidated_precision_at_k",
    "unvalidated_recall_at_k",
    "unvalidated_mrr",
    "unvalidated_ndcg",
]


def upgrade() -> None:
    """Upgrade schema."""
    # Per-pair scores live in the run's results.json artifact from now on - the
    # detail tables only ever served the per-run display, which reads that JSON.
    op.drop_table("evaluation_result_sources")
    op.drop_table("evaluation_results")
    with op.batch_alter_table("evaluation_runs") as batch:
        for column in _METRIC_COLUMNS:
            batch.drop_column(column)
        # RustFS object keys of the promptfoo artifacts - NULL on the runs
        # predating this migration (their scores are lost, accepted).
        batch.add_column(sa.Column("results_json_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("report_html_key", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("evaluation_runs") as batch:
        batch.drop_column("report_html_key")
        batch.drop_column("results_json_key")
        for column in reversed(_METRIC_COLUMNS):
            batch.add_column(sa.Column(column, sa.Float(), nullable=True))
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("qa_pair_id", sa.UUID(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=False),
        sa.Column("generated_answer", sa.Text(), nullable=False),
        sa.Column("validated", sa.Boolean(), nullable=False),
        sa.Column("golden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("precision_at_k", sa.Float(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=False),
        sa.Column("reciprocal_rank", sa.Float(), nullable=False),
        sa.Column("ndcg", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["qa_pair_id"], ["qa_pairs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_results_run_id", "evaluation_results", ["run_id"])
    op.create_table(
        "evaluation_result_sources",
        sa.Column("evaluation_result_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_result_id"],
            ["evaluation_results.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("evaluation_result_id", "source"),
    )
