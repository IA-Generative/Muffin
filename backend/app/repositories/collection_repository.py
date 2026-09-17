import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.collection import Collection, CollectionSettings, CollectionTag
from app.models.document import Document, DocumentPage


class CollectionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _base_query(self):
        return select(Collection).options(selectinload(Collection.tags), selectinload(Collection.settings))

    async def list_by_owner(self, owner_id: str, *, limit: int, offset: int) -> tuple[Sequence[Collection], int]:
        # Owner only for now, not CollectionShare: a collection shared with this
        # user (or one of their groups) won't show up yet. Deliberately deferred -
        # group-based sharing also needs Keycloak groups added to RequestContext,
        # which isn't there yet either.
        where = Collection.owner_id == owner_id

        total = await self.db.scalar(select(func.count()).select_from(Collection).where(where))

        result = await self.db.execute(
            self._base_query().where(where).order_by(Collection.updated_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all(), total or 0

    async def get(self, collection_id: uuid.UUID, owner_id: str) -> Collection | None:
        result = await self.db.execute(
            self._base_query().where(Collection.id == collection_id, Collection.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def create(self, *, owner_id: str, name: str, embedding_model: str) -> Collection:
        collection = Collection(owner_id=owner_id, name=name, description="")
        collection.settings = CollectionSettings(embedding_model=embedding_model)
        self.db.add(collection)
        await self.db.flush()
        await self.db.refresh(collection, attribute_names=["tags", "settings"])
        return collection

    async def update_name(self, collection: Collection, name: str) -> None:
        collection.name = name

    async def update_description(self, collection: Collection, description: str, updated_by: str) -> None:
        collection.description = description
        collection.description_updated_by = updated_by
        collection.description_updated_at = datetime.now(UTC)

    async def update_tags(self, collection: Collection, tags: list[str], updated_by: str) -> None:
        await self.db.execute(delete(CollectionTag).where(CollectionTag.collection_id == collection.id))
        collection.tags = [CollectionTag(collection_id=collection.id, tag=tag) for tag in dict.fromkeys(tags)]
        collection.tags_updated_by = updated_by
        collection.tags_updated_at = datetime.now(UTC)

    async def list_rustfs_keys(self, collection_id: uuid.UUID) -> list[str]:
        """Every RustFS object under this collection - uploaded files and page
        screenshots - collected before the cascade delete removes the rows
        that reference them."""
        storage_keys = await self.db.scalars(
            select(Document.storage_key).where(
                Document.collection_id == collection_id, Document.storage_key.is_not(None)
            )
        )
        screenshot_keys = await self.db.scalars(
            select(DocumentPage.screenshot)
            .join(Document, DocumentPage.document_id == Document.id)
            .where(Document.collection_id == collection_id, DocumentPage.screenshot.is_not(None))
        )
        return [*storage_keys.all(), *screenshot_keys.all()]

    async def delete(self, collection: Collection) -> None:
        await self.db.delete(collection)
