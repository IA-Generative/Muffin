from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.group import ResourceSource
from app.repositories.document_sync_repository import CollectionNotSyncedError, DocumentSyncRepository
from app.schemas.document_sync import DocumentSyncIn, DocumentSyncOut

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
    return DocumentSyncOut(
        id=result.document.id,
        created=result.created,
        chunks_written=result.chunks_written,
        chunks_removed=result.chunks_removed,
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
    if not await DocumentSyncRepository(db).delete(source, external_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such file")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
