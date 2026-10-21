import uuid

from pydantic import BaseModel

from app.models.collection import ChunkingStrategy


class EvaluationQaPairOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    # Retrieval relevance can only be judged at document granularity - a QaPair has no
    # chunk-level ground truth (see app/models/qa.py) - so a pair with no source document has
    # nothing to score against and the worker skips it.
    document_id: uuid.UUID | None
    # Both validated and not-yet-validated pairs get evaluated (see EvaluationRun's docstring) -
    # this is what the worker groups its validated_*/unvalidated_* aggregates by.
    validated: bool
    # A test question (#260): the worker reports its scores apart from the other pairs'.
    golden: bool = False
    # Every document that holds the answer (a golden pair, which can span several) - what a retrieved
    # chunk is judged against. Empty: the pair's own document_id is the only relevant one.
    relevant_document_ids: list[uuid.UUID] = []


class EvaluationResultIn(BaseModel):
    qa_pair_id: uuid.UUID | None
    question: str
    expected_answer: str
    generated_answer: str
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    ndcg: float
    # Snapshot of EvaluationQaPairOut.validated at evaluation time - never re-derived from the
    # QaPair later (see EvaluationResult.validated's own docstring).
    validated: bool
    # Snapshot of EvaluationQaPairOut.golden at evaluation time, for the same reason.
    golden: bool = False
    # One label per retrieved source (e.g. "handbook.pdf#3") - EvaluationResultSource is a plain
    # detail table, not a foreign key into chunks (a chunk can be deleted/re-chunked later, the
    # record of what this run actually saw should survive that).
    retrieved_sources: list[str] = []


class EvaluationRunCreate(BaseModel):
    k: int
    pair_count: int
    llm_model: str
    snapshot_chunking_strategy: ChunkingStrategy
    snapshot_chunk_size: int
    snapshot_chunk_overlap: int
    snapshot_embedding_model: str
    # Global aggregate over the pairs that aren't golden, validated and not - None when the run only
    # had golden pairs.
    precision_at_k: float | None
    recall_at_k: float | None
    mrr: float | None
    ndcg: float | None
    # The golden pairs, scored apart (#260) - None when there are none.
    golden_pair_count: int = 0
    golden_precision_at_k: float | None = None
    golden_recall_at_k: float | None = None
    golden_mrr: float | None = None
    golden_ndcg: float | None = None
    # Same four metrics, broken down by EvaluationResultIn.validated - None when that subset is
    # empty (see EvaluationRun's docstring).
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
    # SHA-256 of (QA pairs + chunking settings + embedding model + k + llm_model) - the worker
    # computes this before running and checks /evaluation-runs/exists to skip if an identical run
    # already exists (same dedup strategy as DiscussionScore.content_hash).
    content_hash: str
    results: list[EvaluationResultIn]
