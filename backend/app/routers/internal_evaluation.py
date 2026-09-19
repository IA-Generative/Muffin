import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.schemas.internal_evaluation import EvaluationQaPairOut, EvaluationRunCreate

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


@router.get(
    "/collections/{collection_id}/qa-pairs",
    summary="List every QA pair of a collection, validated or not - what worker/evaluation "
    "replays retrieval against, grouping its aggregates by EvaluationQaPairOut.validated",
    response_model=list[EvaluationQaPairOut],
)
async def list_qa_pairs_for_evaluation(
    collection_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[EvaluationQaPairOut]:
    if await CollectionRepository(db).get_by_id(collection_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    pairs = await QaPairRepository(db).list_by_collection(collection_id)
    return [
        EvaluationQaPairOut(
            id=pair.id,
            question=pair.question,
            answer=pair.answer,
            document_id=pair.document_id,
            validated=pair.validated,
        )
        for pair in pairs
    ]


@router.get(
    "/documents/{document_id}/chunk-count",
    summary="Number of chunks a document has - the recall@k denominator for retrieval evaluation "
    "(see ChunkRepository.count_by_document)",
)
async def get_document_chunk_count(
    document_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, int]:
    if await DocumentRepository(db).get(document_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    count = await ChunkRepository(db).count_by_document(document_id)
    return {"count": count}


@router.post(
    "/collections/{collection_id}/evaluation-runs",
    summary="Record a completed retrieval-evaluation run and its per-pair results (see #11)",
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_run(
    collection_id: uuid.UUID,
    body: EvaluationRunCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    if await CollectionRepository(db).get_by_id(collection_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    run = await EvaluationRepository(db).create_run(collection_id, body.model_dump(mode="python"))
    await db.commit()
    return {"status": "ok", "id": str(run.id)}


@router.get(
    "/collections/{collection_id}/evaluation-runs/exists",
    summary="Check whether an evaluation run already exists for this (content_hash, llm_model) pair - "
    "lets the worker skip re-evaluating an unchanged collection with the same model (see #11)",
)
async def find_evaluation_run(
    collection_id: uuid.UUID,
    content_hash: str,
    llm_model: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str | None]:
    existing_id = await EvaluationRepository(db).find_existing(collection_id, content_hash, llm_model)
    return {"id": str(existing_id) if existing_id else None}
