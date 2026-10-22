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


class EvaluationRunCreate(BaseModel):
    """A completed promptfoo run's metadata - the scores themselves are not posted
    here: they live in the run's results.json artifact, uploaded right after via
    /evaluation-runs/{run_id}/artifacts (see docs/promptfoo-evaluation-plan.md)."""

    k: int
    pair_count: int
    # The judge model (the collection's "evaluation" generation model).
    llm_model: str
    snapshot_chunking_strategy: ChunkingStrategy
    snapshot_chunk_size: int
    snapshot_chunk_overlap: int
    snapshot_embedding_model: str
    # The golden (test) pairs, scored apart (#260).
    golden_pair_count: int = 0
    # Breakdown by QaPair.validated at evaluation time - never re-derived from the
    # (possibly since-changed) QaPair later.
    validated_pair_count: int
    unvalidated_pair_count: int
    # SHA-256 of (QA pairs + chunking settings + embedding model + k + judge model +
    # generator model) - the worker computes this before running and checks
    # /evaluation-runs/exists to skip if an identical run already exists (same dedup
    # strategy as DiscussionScore.content_hash).
    content_hash: str
