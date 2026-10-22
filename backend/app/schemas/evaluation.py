import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.collection import ChunkingStrategy


class EvaluationTriggerRequest(BaseModel):
    # How many chunks the worker retrieves per question - same meaning as any other search's
    # `limit` (see worker/agent_execution's MAX_PARALLEL_SEARCHES-style budgets), just for the
    # evaluation's own retrieval pass rather than a live agent run.
    k: int = 5
    # When True (default), only validated QA pairs are evaluated. When False, all QA pairs
    # with a source document are evaluated - lets the user run evaluation on unvalidated
    # pairs too (the validated/unvalidated breakdown in EvaluationRun still separates them).
    validated_only: bool = False


class EvaluationMetricsOut(BaseModel):
    """A run's factuality averages, computed from its results.json artifact at read
    time (see app/services/evaluation_artifacts.py) - not stored in the database."""

    factuality: float | None


class EvaluationResultOut(BaseModel):
    """One QA pair's outcome in a run, normalized from the results.json artifact -
    the frontend never parses promptfoo's format itself."""

    qa_pair_id: str | None
    question: str
    expected_answer: str
    generated_answer: str
    # None when the judge errored on this pair (no namedScores entry).
    factuality: float | None
    validated: bool
    golden: bool = False
    retrieved_sources: list[str]


class EvaluationRunOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    created_at: datetime
    k: int
    pair_count: int
    # The judge model (the collection's "evaluation" generation model).
    llm_model: str
    snapshot_chunking_strategy: ChunkingStrategy
    snapshot_chunk_size: int
    snapshot_chunk_overlap: int
    snapshot_embedding_model: str
    # The golden (test) pairs, scored apart - the numbers to follow over time.
    golden_pair_count: int = 0
    validated_pair_count: int
    unvalidated_pair_count: int
    # SHA-256 of (QA pairs + chunking settings + embedding model + k + judge model + generator
    # model) - present when the worker computed it for dedup (see EvaluationRun.content_hash).
    content_hash: str | None = None
    # Factuality averages over the non-golden / golden pairs - None when that subset is
    # empty, or when the run predates the promptfoo migration (no artifact).
    metrics: EvaluationMetricsOut | None
    golden_metrics: EvaluationMetricsOut | None
    # Whether the report/results.json artifacts exist (download links, report preview) -
    # False on the runs predating the promptfoo migration.
    has_artifacts: bool
