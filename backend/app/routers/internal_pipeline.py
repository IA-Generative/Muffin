import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.document_stage import PipelineStage
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.entity_repository import Occurrence, RelationSource
from app.schemas.internal_pipeline import EntityWindowReplace, GeneratedQaReplace
from app.services.document_derived_data import DocumentDerivedData
from app.services.document_derived_data import GeneratedQaPair as GeneratedQaPairData
from app.services.result_reuse import ResultReuse

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


async def _ensure_collection(db: AsyncSession, collection_id: uuid.UUID) -> None:
    if await CollectionRepository(db).get_by_id(collection_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")


@router.put(
    "/collections/{collection_id}/qa-pairs/generated",
    summary="Record the question/answer pairs one run of the pipeline generated, replacing the previous "
    "run's of the same key",
)
async def replace_generated_qa(
    collection_id: uuid.UUID, body: GeneratedQaReplace, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    await _ensure_collection(db, collection_id)
    await DocumentDerivedData(db).replace_generated_qa(
        collection_id,
        body.document_id,
        body.key,
        [GeneratedQaPairData(**pair.model_dump()) for pair in body.pairs],
    )
    await db.commit()
    # The window is one piece of the document's QA stage (#300).
    if body.document_id is not None and body.key.startswith("window:"):
        await ResultReuse(db).mark_done(body.document_id, PipelineStage.QA, body.key)
    return {"status": "ok"}


@router.put(
    "/documents/{document_id}/entity-windows/{window_key}",
    summary="Record the entities and relations extracted from one window of a document's pages, replacing "
    "what the previous extraction of that window recorded",
)
async def replace_entity_window(
    document_id: uuid.UUID,
    window_key: str,
    body: EntityWindowReplace,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    document = await DocumentRepository(db).get(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await DocumentDerivedData(db).replace_entity_window(
        document.collection_id,
        document_id,
        window_key,
        [
            (
                entity.name,
                entity.type.value,
                entity.mentions,
                [Occurrence(o.page, o.start, o.end) for o in entity.occurrences if o.end > o.start],
            )
            for entity in body.entities
        ],
        [
            (
                relation.from_name,
                relation.to_name,
                relation.type,
                RelationSource(
                    relation.source_page, relation.source_excerpt, relation.source_start, relation.source_end
                )
                if relation.source_page and relation.source_excerpt
                else None,
            )
            for relation in body.relations
        ],
    )
    await db.commit()
    await ResultReuse(db).mark_done(document_id, PipelineStage.ENTITIES, window_key)
    return {"status": "ok"}
