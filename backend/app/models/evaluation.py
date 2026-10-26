import uuid

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.collection import ChunkingStrategy


class EvaluationRun(UUIDMixin, TimestampMixin, Base):
    """An evaluation run against a collection's QA pairs, executed by promptfoo in
    worker/evaluation (see docs/promptfoo-evaluation-plan.md) - both validated and
    not-yet-validated pairs are evaluated, so a low score can be told apart from
    "these questions were never reviewed" rather than looking like a quality problem.

    The scores themselves are not stored here: the run's promptfoo artifacts
    (results.json / report.html) in RustFS are the source of truth, read back at
    display time - see results_json_key / report_html_key."""

    __tablename__ = "evaluation_runs"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    k: Mapped[int] = mapped_column(Integer, nullable=False)
    # Every evaluated pair, validated and not - see validated_pair_count/unvalidated_pair_count
    # for the breakdown.
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # The judge model (the collection's "evaluation" generation model) - what the
    # metric scores were produced with.
    llm_model: Mapped[str] = mapped_column(String, nullable=False)

    # Chunking/embedding config snapshot at run time, since collection settings can change afterwards.
    snapshot_chunking_strategy: Mapped[ChunkingStrategy] = mapped_column(
        Enum(ChunkingStrategy, name="chunking_strategy"), nullable=False
    )
    snapshot_chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_embedding_model: Mapped[str] = mapped_column(String, nullable=False)

    # The golden pairs (#260), the scores worth following over time: human-written, never in the
    # retriever. Their score averages are reported apart from the other pairs'.
    golden_pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Snapshot of QaPair.validated at evaluation time - what the run's validated/unvalidated
    # breakdown is grouped by, never re-derived from the (possibly since-changed) QaPair.
    validated_pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unvalidated_pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # RustFS object keys of the run's promptfoo artifacts - NULL on the runs predating the
    # promptfoo migration (their scores are lost, accepted) and until the worker uploads
    # them right after creating the run.
    results_json_key: Mapped[str | None] = mapped_column(String, nullable=True)
    report_html_key: Mapped[str | None] = mapped_column(String, nullable=True)

    # SHA-256 of (QA pairs content + chunking settings + embedding model + k + judge model +
    # generator model + scored metrics) - lets the worker skip re-evaluating a collection when
    # nothing that affects the result has changed since the last run with the same parameters
    # (same strategy as DiscussionScore's content_hash, see #31).
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index(
            "uq_evaluation_runs_collection_hash",
            "collection_id",
            "content_hash",
            "llm_model",
            unique=True,
            postgresql_where=sa_text("content_hash IS NOT NULL"),
        ),
    )

    collection: Mapped["Collection"] = relationship(back_populates="evaluation_runs")  # noqa: F821
