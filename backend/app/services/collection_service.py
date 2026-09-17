import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.factory import RequestContext
from app.models.collection import Collection
from app.repositories.collection_repository import CollectionRepository
from app.schemas.collection import CollectionOut, CollectionSettingsUpdate, CollectionUpdate
from app.schemas.pagination import Page, PaginationParams

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_COLLECTION_NAME = "Nouvelle collection"


class CollectionNotFoundError(Exception):
    pass


def _display_name(user: RequestContext) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name or user.email


class CollectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = CollectionRepository(db)

    async def list_collections(self, user: RequestContext, pagination: PaginationParams) -> Page[CollectionOut]:
        collections, total = await self.repository.list_by_owner(
            user.user_id, limit=pagination.limit, offset=pagination.offset
        )
        return pagination.to_page([CollectionOut.from_model(collection) for collection in collections], total)

    async def create_collection(self, user: RequestContext) -> CollectionOut:
        collection = await self.repository.create(
            owner_id=user.user_id, name=DEFAULT_COLLECTION_NAME, embedding_model=DEFAULT_EMBEDDING_MODEL
        )
        await self.db.commit()
        return CollectionOut.from_model(collection)

    async def get_collection(self, collection_id: uuid.UUID, user: RequestContext) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)
        return CollectionOut.from_model(collection)

    async def update_collection(
        self, collection_id: uuid.UUID, user: RequestContext, update: CollectionUpdate
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)
        updated_by = _display_name(user)

        if update.name is not None and update.name.strip():
            await self.repository.update_name(collection, update.name.strip())
        if update.description is not None:
            await self.repository.update_description(collection, update.description, updated_by)
        if update.tags is not None:
            await self.repository.update_tags(collection, update.tags, updated_by)

        await self.db.commit()
        # tags/settings are already correct in memory (mutated directly above),
        # this is only to reload updated_at - onupdate=func.now() expires it
        # after the UPDATE, and accessing it later outside an active await
        # crashes with MissingGreenlet instead of lazy-loading like sync ORM would.
        await self.db.refresh(collection, attribute_names=["updated_at"])
        return CollectionOut.from_model(collection)

    async def update_settings(
        self, collection_id: uuid.UUID, user: RequestContext, update: CollectionSettingsUpdate
    ) -> CollectionOut:
        collection = await self._get_owned(collection_id, user)

        await self.repository.update_settings(
            collection,
            chunking_strategy=update.chunking_strategy,
            chunk_size=update.chunk_size,
            chunk_overlap=update.chunk_overlap,
            embedding_model=update.embedding_model,
            instructions=update.instructions.model_dump() if update.instructions is not None else None,
            # exclude_unset, not model_dump(): only the keys the caller sent
            # should be merged in - the schema defaults every field to None,
            # so a full dump would overwrite the others with None too.
            generation_models=(
                update.generation_models.model_dump(exclude_unset=True)
                if update.generation_models is not None
                else None
            ),
        )

        # No refresh needed: only collection_settings columns changed (none
        # with a server-side onupdate), so nothing on `collection` is expired.
        await self.db.commit()
        return CollectionOut.from_model(collection)

    async def delete_collection(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        collection = await self._get_owned(collection_id, user)
        # Collected before the cascade delete removes the rows that reference
        # them - Postgres cleanup and RustFS cleanup can't be one transaction.
        rustfs_keys = await self.repository.list_rustfs_keys(collection_id)
        await self.repository.delete(collection)
        await self.db.commit()
        # Best-effort and after the commit: a RustFS failure here must not
        # roll back a deletion the user already sees as done.
        # TODO: also delete this collection's vectors once Qdrant exists.
        storage.delete_objects(rustfs_keys)

    async def _get_owned(self, collection_id: uuid.UUID, user: RequestContext) -> Collection:
        collection = await self.repository.get(collection_id, user.user_id)
        if collection is None:
            raise CollectionNotFoundError(str(collection_id))
        return collection
