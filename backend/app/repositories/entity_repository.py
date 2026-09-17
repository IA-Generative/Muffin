import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entity import Entity, EntityType, Relation


class EntityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert(self, collection_id: uuid.UUID, name: str, type_: str, mentions_delta: int) -> Entity:
        result = await self.db.execute(
            select(Entity).where(
                Entity.collection_id == collection_id, Entity.name == name, Entity.type == EntityType(type_)
            )
        )
        entity = result.scalar_one_or_none()
        if entity is None:
            entity = Entity(collection_id=collection_id, name=name, type=EntityType(type_), mentions=mentions_delta)
            self.db.add(entity)
        else:
            entity.mentions += mentions_delta
        await self.db.flush()
        return entity

    async def create_relation(
        self, collection_id: uuid.UUID, from_entity_id: uuid.UUID, to_entity_id: uuid.UUID, type_: str
    ) -> Relation:
        relation = Relation(
            collection_id=collection_id, from_entity_id=from_entity_id, to_entity_id=to_entity_id, type=type_
        )
        self.db.add(relation)
        await self.db.flush()
        return relation

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[Entity]:
        result = await self.db.execute(
            select(Entity).where(Entity.collection_id == collection_id).order_by(Entity.mentions.desc())
        )
        return result.scalars().all()

    async def list_relations_by_collection(self, collection_id: uuid.UUID) -> Sequence[Relation]:
        result = await self.db.execute(
            select(Relation)
            .where(Relation.collection_id == collection_id)
            .options(selectinload(Relation.from_entity), selectinload(Relation.to_entity))
        )
        return result.scalars().all()
