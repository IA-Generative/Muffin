import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_import import CollectionImport


class CollectionImportRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, collection_import: CollectionImport) -> CollectionImport:
        self.db.add(collection_import)
        await self.db.flush()
        return collection_import

    async def get(self, import_id: uuid.UUID, owner_id: str) -> CollectionImport | None:
        result = await self.db.execute(
            select(CollectionImport).where(CollectionImport.id == import_id, CollectionImport.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, import_id: uuid.UUID) -> CollectionImport | None:
        """No owner check - internal/worker use only."""
        return await self.db.get(CollectionImport, import_id)

    async def root_collection_ids_for_conversation(self, conversation_id: uuid.UUID) -> Sequence[uuid.UUID]:
        """The collections created from ZIPs dropped into this conversation (#223) - pinned to its
        runs like its temporary collection, see RunService.create_run."""
        result = await self.db.scalars(
            select(CollectionImport.root_collection_id).where(
                CollectionImport.conversation_id == conversation_id,
                CollectionImport.root_collection_id.is_not(None),
            )
        )
        return result.all()
