import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.collection import ChunkingStrategy


class EvaluationTriggerRequest(BaseModel):
    # How many chunks the worker retrieves per question - same meaning as any other search's
    # `limit` (see worker/agent_execution's MAX_PARALLEL_SEARCHES-style budgets), just for the
    # evaluation's own retrieval pass rather than a live agent run.
    k: int = 5


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
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg: float
    results: list[EvaluationResultOut]
