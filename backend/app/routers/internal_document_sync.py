from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.group import ResourceSource
from app.repositories.document_sync_repository import CollectionNotSyncedError, DocumentSyncRepository
from app.schemas.document_sync import DocumentSyncIn, DocumentSyncOut
from app.services import vector_store

router = APIRouter(
    prefix="/internal/synced-documents",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


@router.put("/{source}/{external_id:path}", summary="Make the copy of a file of another system what that system has")
async def sync_document(
    source: ResourceSource, external_id: str, body: DocumentSyncIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> DocumentSyncOut:
    if source == ResourceSource.MUFFIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The files made in Muffin are not synchronised")
    try:
        result = await DocumentSyncRepository(db).sync(source, external_id, body)
    except CollectionNotSyncedError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Collection {error} is not synchronised yet") from error
    await db.commit()
    if result.summary_dropped:
        # Best-effort, like every cleanup of the index: the point is made again with the new summary.
        vector_store.delete_document_embeddings(result.document.collection_id, result.document.id, [])
    return DocumentSyncOut(
        id=result.document.id,
        collection_id=result.document.collection_id,
        created=result.created,
        chunks_written=result.chunks_written,
        chunks_removed=result.chunks_removed,
        summary_due=result.summary_due,
    )


@router.get("/{source}", summary="The ids, in another system, of the files copied from it")
async def list_external_ids(source: ResourceSource, db: Annotated[AsyncSession, Depends(get_db)]) -> list[str]:
    if source == ResourceSource.MUFFIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The files made in Muffin are not synchronised")
    return await DocumentSyncRepository(db).external_ids(source)


@router.delete(
    "/{source}/{external_id:path}", status_code=status.HTTP_204_NO_CONTENT, summary="Drop the copy of a file"
)
async def delete_document(
    source: ResourceSource, external_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> Response:
    if source == ResourceSource.MUFFIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The files made in Muffin are not synchronised")
    deleted = await DocumentSyncRepository(db).delete(source, external_id)
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file")
    await db.commit()
    # Its summary is the one point of Muffin's index a copied file has (#457); its chunks are Open WebUI's.
    vector_store.delete_document_embeddings(*deleted, [])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
