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


class EvaluationResultSourceOut(BaseModel):
    source: str


class EvaluationResultOut(BaseModel):
    id: uuid.UUID
    qa_pair_id: uuid.UUID | None
    question: str
    expected_answer: str
    generated_answer: str
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    ndcg: float
    validated: bool
    retrieved_sources: list[str]


class EvaluationRunOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    created_at: datetime
    k: int
    pair_count: int
    llm_model: str
    snapshot_chunking_strategy: ChunkingStrategy
    snapshot_chunk_size: int
    snapshot_chunk_overlap: int
    snapshot_embedding_model: str
    # Global aggregate - every evaluated pair, validated and not.
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg: float
    # Same four metrics, broken down by whether the QA pair was validated at evaluation time -
    # None when that subset is empty (see EvaluationRun's own docstring).
    validated_pair_count: int
    validated_precision_at_k: float | None
    validated_recall_at_k: float | None
    validated_mrr: float | None
    validated_ndcg: float | None
    unvalidated_pair_count: int
    unvalidated_precision_at_k: float | None
    unvalidated_recall_at_k: float | None
    unvalidated_mrr: float | None
    unvalidated_ndcg: float | None
    # SHA-256 of (QA pairs + chunking settings + embedding model + k + llm_model) - present when
    # the worker computed it for dedup (see EvaluationRun.content_hash).
    content_hash: str | None = None
    results: list[EvaluationResultOut]
