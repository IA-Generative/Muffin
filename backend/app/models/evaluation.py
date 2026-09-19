import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.collection import ChunkingStrategy


class EvaluationRun(UUIDMixin, TimestampMixin, Base):
    """A retrieval-evaluation run against a collection's QA pairs - both validated and
    not-yet-validated ones are evaluated (see EvaluationResult.validated), so a low score can be
    told apart from "these questions were never reviewed" rather than looking like a retrieval
    problem."""

    __tablename__ = "evaluation_runs"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    k: Mapped[int] = mapped_column(Integer, nullable=False)
    # Every evaluated pair, validated and not - see validated_pair_count/unvalidated_pair_count
    # for the breakdown.
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)

    # Chunking/embedding config snapshot at run time, since collection settings can change afterwards.
    snapshot_chunking_strategy: Mapped[ChunkingStrategy] = mapped_column(
        Enum(ChunkingStrategy, name="chunking_strategy"), nullable=False
    )
    snapshot_chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_embedding_model: Mapped[str] = mapped_column(String, nullable=False)

    # Global aggregate - every evaluated pair, validated and not.
    precision_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    recall_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    mrr: Mapped[float] = mapped_column(Float, nullable=False)
    ndcg: Mapped[float] = mapped_column(Float, nullable=False)

    # Same four metrics, computed separately over just the validated subset and just the
    # not-yet-validated one - nullable, since a run can end up with one subset empty (e.g. a
    # collection with no validated pairs yet). Never derived from a live join to QaPair.validated
    # at read time: a pair can be validated/deleted after the fact, and this run should keep
    # reflecting what was true when it actually ran (same reasoning as qa_pair_id being nullable
    # below while question/expected_answer stay snapshotted).
    validated_pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validated_precision_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    validated_recall_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    validated_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    validated_ndcg: Mapped[float | None] = mapped_column(Float, nullable=True)
    unvalidated_pair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unvalidated_precision_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    unvalidated_recall_at_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    unvalidated_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    unvalidated_ndcg: Mapped[float | None] = mapped_column(Float, nullable=True)

    collection: Mapped["Collection"] = relationship(back_populates="evaluation_runs")  # noqa: F821
    results: Mapped[list["EvaluationResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvaluationResult(UUIDMixin, Base):
    """Per-QA-pair scores for one evaluation run."""

    __tablename__ = "evaluation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Nullable: the QA pair may be edited/deleted later, the question/answer snapshot below stays intact.
    qa_pair_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("qa_pairs.id", ondelete="SET NULL"), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False)
    generated_answer: Mapped[str] = mapped_column(Text, nullable=False)
    # Snapshot of QaPair.validated at evaluation time - what the run's validated/unvalidated
    # aggregates above are grouped by, never re-derived from the (possibly since-changed) QaPair.
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    precision_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    recall_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    reciprocal_rank: Mapped[float] = mapped_column(Float, nullable=False)
    ndcg: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped["EvaluationRun"] = relationship(back_populates="results")
    qa_pair: Mapped["QaPair | None"] = relationship()  # noqa: F821
    retrieved_sources: Mapped[list["EvaluationResultSource"]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )


class EvaluationResultSource(Base):
    """Detail table: sources retrieved for one evaluation result."""

    __tablename__ = "evaluation_result_sources"

    evaluation_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_results.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String, primary_key=True)

    result: Mapped["EvaluationResult"] = relationship(back_populates="retrieved_sources")
