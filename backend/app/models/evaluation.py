import uuid

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.collection import ChunkingStrategy


class EvaluationRun(UUIDMixin, TimestampMixin, Base):
    """A retrieval-evaluation run against a collection's validated QA pairs."""

    __tablename__ = "evaluation_runs"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    k: Mapped[int] = mapped_column(Integer, nullable=False)
    pair_count: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)

    # Chunking/embedding config snapshot at run time, since collection settings can change afterwards.
    snapshot_chunking_strategy: Mapped[ChunkingStrategy] = mapped_column(
        Enum(ChunkingStrategy, name="chunking_strategy"), nullable=False
    )
    snapshot_chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_embedding_model: Mapped[str] = mapped_column(String, nullable=False)

    # Aggregate metrics across all results of the run.
    precision_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    recall_at_k: Mapped[float] = mapped_column(Float, nullable=False)
    mrr: Mapped[float] = mapped_column(Float, nullable=False)
    ndcg: Mapped[float] = mapped_column(Float, nullable=False)

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
