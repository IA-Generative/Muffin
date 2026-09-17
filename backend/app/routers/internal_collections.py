import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.collection_repository import CollectionRepository
from app.schemas.internal_pipeline import CollectionSettingsInternalOut

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


@router.get(
    "/collections/{collection_id}/settings",
    summary="Fetch a collection's pipeline settings for the worker to run chunking/summary/QA/extraction/tagging",
    response_model=CollectionSettingsInternalOut,
)
async def get_collection_settings(
    collection_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> CollectionSettingsInternalOut:
    collection = await CollectionRepository(db).get_by_id(collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    settings = collection.settings
    return CollectionSettingsInternalOut(
        chunking_strategy=settings.chunking_strategy,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        embedding_model=settings.embedding_model,
        instructions={
            "qa": settings.instructions_qa,
            "extraction": settings.instructions_extraction,
            "chunking": settings.instructions_chunking,
            "tagging": settings.instructions_tagging,
            "summary": settings.instructions_summary,
        },
        generation_models=settings.generation_models or {},
        pipeline_windows=settings.pipeline_windows or {},
    )
