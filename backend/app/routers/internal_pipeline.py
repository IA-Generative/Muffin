import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.collection_repository import CollectionRepository
from app.repositories.entity_repository import EntityRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.schemas.internal_pipeline import EntityCreate, EntityOut, QaPairCreate, RelationCreate

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


async def _ensure_collection(db: AsyncSession, collection_id: uuid.UUID) -> None:
    if await CollectionRepository(db).get_by_id(collection_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")


@router.post(
    "/collections/{collection_id}/qa-pairs",
    summary="Record a generated question/answer pair",
    status_code=status.HTTP_201_CREATED,
)
async def create_qa_pair(
    collection_id: uuid.UUID, body: QaPairCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    await _ensure_collection(db, collection_id)
    await QaPairRepository(db).create(collection_id, body.document_id, body.question, body.answer)
    await db.commit()
    return {"status": "ok"}


@router.post(
    "/collections/{collection_id}/entities",
    summary="Upsert an extracted entity (creates it, or bumps its mention count if it already exists)",
    response_model=EntityOut,
)
async def upsert_entity(
    collection_id: uuid.UUID, body: EntityCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> EntityOut:
    await _ensure_collection(db, collection_id)
    entity = await EntityRepository(db).upsert(collection_id, body.name, body.type, body.mentions_delta)
    await db.commit()
    return EntityOut(id=entity.id, name=entity.name, type=entity.type, mentions=entity.mentions)


@router.post(
    "/collections/{collection_id}/relations",
    summary="Record a relation between two previously-upserted entities",
    status_code=status.HTTP_201_CREATED,
)
async def create_relation(
    collection_id: uuid.UUID, body: RelationCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    await _ensure_collection(db, collection_id)
    await EntityRepository(db).create_relation(collection_id, body.from_entity_id, body.to_entity_id, body.type)
    await db.commit()
    return {"status": "ok"}
