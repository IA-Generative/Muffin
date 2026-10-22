import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection
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

    async def get_locked(self, import_id: uuid.UUID) -> CollectionImport | None:
        """Locked until the end of the transaction: the batches of a big import report as they finish, at
        the same time, and a read-modify-write of what they report would lose some."""
        result = await self.db.execute(
            select(CollectionImport)
            .where(CollectionImport.id == import_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self, owner_id: str, *, conversation_id: uuid.UUID | None = None, awaiting_attachment: bool = False
    ) -> Sequence[CollectionImport]:
        """Most recent first. `awaiting_attachment`: the ones with an attach suggestion the user
        hasn't answered yet - eligible, not dismissed, a suggestion computed, and the collection
        still at the top level."""
        query = select(CollectionImport).where(CollectionImport.owner_id == owner_id)
        if conversation_id is not None:
            query = query.where(CollectionImport.conversation_id == conversation_id)
        if awaiting_attachment:
            query = query.join(Collection, Collection.id == CollectionImport.root_collection_id).where(
                CollectionImport.attach_eligible.is_(True),
                CollectionImport.attach_dismissed.is_(False),
                CollectionImport.suggested_parent_id.is_not(None),
                Collection.parent_id.is_(None),
            )
        result = await self.db.scalars(query.order_by(CollectionImport.created_at.desc()))
        return result.all()

    async def get_by_root_collection(self, collection_id: uuid.UUID) -> CollectionImport | None:
        result = await self.db.scalars(
            select(CollectionImport).where(CollectionImport.root_collection_id == collection_id).limit(1)
        )
        return result.first()

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
