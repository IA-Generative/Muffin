from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.group import ResourceSource
from app.repositories.collection_repository import CollectionRepository
from app.repositories.collection_sync_repository import CollectionSyncRepository
from app.schemas.collection_sync import CollectionSyncIn, CollectionSyncOut
from app.services import vector_store

router = APIRouter(
    prefix="/internal/synced-collections",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


def _copied_source(source: ResourceSource) -> ResourceSource:
    """Only the collections copied from another system are the synchronisation's to write, not the ones made here."""
    if source == ResourceSource.MUFFIN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The collections made in Muffin are not synchronised")
    return source


@router.put("/{source}/{external_id}", summary="Make the copy of a collection of another system what that system has")
async def sync_collection(
    source: ResourceSource, external_id: str, body: CollectionSyncIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> CollectionSyncOut:
    result = await CollectionSyncRepository(db).sync(_copied_source(source), external_id, body)
    await db.commit()
    return CollectionSyncOut(
        id=result.collection.id,
        created=result.created,
        shares_added=result.shares_added,
        shares_removed=result.shares_removed,
        shares_updated=result.shares_updated,
        unknown_groups=result.unknown_groups,
        skipped=result.skipped,
    )


@router.get("/{source}", summary="The ids, in another system, of the collections copied from it")
async def list_external_ids(source: ResourceSource, db: Annotated[AsyncSession, Depends(get_db)]) -> list[str]:
    return await CollectionSyncRepository(db).external_ids(_copied_source(source))


@router.delete(
    "/{source}/{external_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Drop the copy of a collection"
)
async def delete_collection(
    source: ResourceSource, external_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> Response:
    repository = CollectionSyncRepository(db)
    collection = await repository.get(_copied_source(source), external_id)
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such collection")
    if await repository.is_held(collection):
        # Muffin took it over (#462): what it holds is its own now, whatever the other system says.
        raise HTTPException(status.HTTP_409_CONFLICT, "Muffin took this collection over")
    collection_id = collection.id
    keys = await CollectionRepository(db).list_rustfs_keys([collection_id])
    await repository.delete(source, external_id)
    await db.commit()
    # After the commit and best-effort, as when a collection is deleted in Muffin; foreign objects are skipped.
    storage.delete_objects(keys)
    vector_store.delete_collection(collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
