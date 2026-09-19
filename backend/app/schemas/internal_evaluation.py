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


class EvaluationResultIn(BaseModel):
    qa_pair_id: uuid.UUID | None
    question: str
    expected_answer: str
    generated_answer: str
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    ndcg: float
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
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg: float
    results: list[EvaluationResultIn]
