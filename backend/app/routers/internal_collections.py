import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.internal_pipeline import (
    CollectionDescriptionEmbeddingUpdate,
    CollectionDescriptionUpdate,
    CollectionMetadataOut,
    CollectionSearchResultOut,
    CollectionSettingsInternalOut,
    CollectionTagsUpdate,
)
from app.schemas.internal_run import SearchRequest
from app.services import vector_store
from app.services.search_service import SearchService

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])

# Automated writes (as opposed to a human editing description/tags in the
# UI) are attributed to this fixed name, same idea as FieldStamp.updated_by
# for a real user - shown as-is in the collection's "last updated by" info.
PIPELINE_UPDATED_BY = "pipeline"


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


@router.get(
    "/collections/{collection_id}/metadata",
    summary="Fetch a collection's current description/tags plus every document summary, for the "
    "description/tags-maintenance tasks to decide whether an update is needed",
    response_model=CollectionMetadataOut,
)
async def get_collection_metadata(
    collection_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> CollectionMetadataOut:
    collection = await CollectionRepository(db).get_by_id(collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    summaries = await DocumentRepository(db).list_summaries_by_collection(collection_id)
    return CollectionMetadataOut(
        description=collection.description,
        tags=[tag.tag for tag in collection.tags],
        document_summaries=list(summaries),
    )


@router.patch(
    "/collections/{collection_id}/description", summary="Report an automatically-maintained collection description"
)
async def update_collection_description(
    collection_id: uuid.UUID, update: CollectionDescriptionUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = CollectionRepository(db)
    collection = await repository.get_by_id(collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    await repository.update_description(collection, update.description, PIPELINE_UPDATED_BY)
    await db.commit()
    return {"status": "ok"}


@router.put("/collections/{collection_id}/tags", summary="Report automatically-maintained collection tags")
async def update_collection_tags(
    collection_id: uuid.UUID, update: CollectionTagsUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = CollectionRepository(db)
    collection = await repository.get_by_id(collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    await repository.update_tags(collection, update.tags, PIPELINE_UPDATED_BY)
    await db.commit()
    # Best-effort, same reasoning as vector_store.delete_collection: a Meilisearch failure here
    # must not roll back the tags themselves, which are already committed above. A no-op if the
    # collection has no description embedded yet (see update_collection_tags_in_index).
    try:
        vector_store.update_collection_tags_in_index(collection_id, update.tags)
    except Exception:
        logger.exception(f"Failed to update tags in the collections search index for {collection_id}")
    return {"status": "ok"}


@router.patch(
    "/collections/{collection_id}/description-embedding",
    summary="Report the embedding vector for a collection's description, indexed in Meilisearch "
    "(§124) to match a query to the right collection - not persisted anywhere in Postgres",
)
async def update_collection_description_embedding(
    collection_id: uuid.UUID,
    update: CollectionDescriptionEmbeddingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    collection = await CollectionRepository(db).get_by_id(collection_id)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    # Best-effort, same reasoning as elsewhere in this router - a Meilisearch failure here must
    # never surface as an error to the worker; the collection's description/tags themselves are
    # unaffected either way, only this search index falls behind until the next successful call.
    try:
        vector_store.upsert_collection_description(
            collection_id, collection.description, [tag.tag for tag in collection.tags], update.embedding
        )
    except Exception:
        logger.exception(f"Failed to index the description for collection {collection_id} in Meilisearch")
    return {"status": "ok"}


@router.post(
    "/collections/search",
    summary="Vector search over collection descriptions, restricted to the given candidate ids - "
    "narrows a large accessible set down to the most relevant collections by embedding similarity, "
    "before an LLM call (§ VDB routing) or a file-filing suggestion (§122)",
    response_model=list[CollectionSearchResultOut],
)
async def search_collections(
    body: SearchRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[CollectionSearchResultOut]:
    rows = await SearchService(db).search_collections(body.collection_ids, body.query, body.limit)
    return [CollectionSearchResultOut(collection_id=collection_id, score=score) for collection_id, score in rows]
