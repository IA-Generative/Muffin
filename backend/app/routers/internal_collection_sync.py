from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.group import ResourceSource
from app.repositories.collection_sync_repository import CollectionSyncRepository
from app.schemas.collection_sync import CollectionSyncIn, CollectionSyncOut

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
        unknown_groups=result.unknown_groups,
    )


@router.get("/{source}", summary="The ids, in another system, of the collections copied from it")
async def list_external_ids(source: ResourceSource, db: Annotated[AsyncSession, Depends(get_db)]) -> list[str]:
    return await CollectionSyncRepository(db).external_ids(_copied_source(source))
