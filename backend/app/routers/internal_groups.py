from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.group import ResourceSource
from app.repositories.group_repository import GroupRepository
from app.schemas.group import GroupSyncIn, GroupSyncOut

router = APIRouter(
    prefix="/internal/groups",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)


def _copied_source(source: ResourceSource) -> ResourceSource:
    """Only the groups copied from another system are the synchronisation's to write, not the ones made here."""
    if source == ResourceSource.MUFFIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The groups made in Muffin are not synchronised"
        )
    return source


@router.put("/{source}/{external_id}", summary="Make the copy of a group of another system what that system has")
async def sync_group(
    source: ResourceSource, external_id: str, body: GroupSyncIn, db: Annotated[AsyncSession, Depends(get_db)]
) -> GroupSyncOut:
    result = await GroupRepository(db).sync_external(
        _copied_source(source), external_id, body.name, body.description, body.member_ids
    )
    await db.commit()
    return GroupSyncOut(
        id=result.group.id,
        created=result.created,
        members_added=result.members_added,
        members_removed=result.members_removed,
    )


@router.get("/{source}", summary="The ids, in another system, of the groups copied from it")
async def list_external_ids(source: ResourceSource, db: Annotated[AsyncSession, Depends(get_db)]) -> list[str]:
    return await GroupRepository(db).external_ids(_copied_source(source))


@router.delete("/{source}/{external_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Drop the copy of a group")
async def delete_group(
    source: ResourceSource, external_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> Response:
    if not await GroupRepository(db).delete_external(_copied_source(source), external_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such group")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
