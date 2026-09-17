import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.collection import Collection, CollectionDescriptionEmbedding, CollectionSettings, CollectionTag
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

    async def list_all_by_owner(self, owner_id: str) -> Sequence[Collection]:
        """Unpaginated - for server-side permission checks (e.g. the research
        agent's "which collections can this user's query even reach"), not
        for a UI listing."""
        result = await self.db.execute(self._base_query().where(Collection.owner_id == owner_id))
        return result.scalars().all()

    async def get(self, collection_id: uuid.UUID, owner_id: str) -> Collection | None:
        result = await self.db.execute(
            self._base_query().where(Collection.id == collection_id, Collection.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, collection_id: uuid.UUID) -> Collection | None:
        """No owner check - internal/worker use only, never exposed on a
        user-facing route."""
        result = await self.db.execute(self._base_query().where(Collection.id == collection_id))
        return result.scalar_one_or_none()

    async def count_documents(self, collection_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many documents each collection has - for the research agent to answer "how many
        documents are in X" without listing them all (§ meta-query tools)."""
        if not collection_ids:
            return {}
        result = await self.db.execute(
            select(Document.collection_id, func.count(Document.id))
            .where(Document.collection_id.in_(collection_ids))
            .group_by(Document.collection_id)
        )
        return dict(result.all())

    async def get_embedding_models(self, collection_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Which embedding model each collection's chunks were embedded with (§12: VDB routing
        picks collections, but the query itself must be embedded once per distinct model among
        them before searching each one's own Qdrant collection)."""
        result = await self.db.execute(
            select(CollectionSettings.collection_id, CollectionSettings.embedding_model).where(
                CollectionSettings.collection_id.in_(collection_ids)
            )
        )
        return dict(result.all())

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

    async def upsert_description_embedding(self, collection_id: uuid.UUID, model: str, embedding: list[float]) -> None:
        existing = await self.db.get(CollectionDescriptionEmbedding, collection_id)
        if existing is None:
            self.db.add(CollectionDescriptionEmbedding(collection_id=collection_id, model=model, embedding=embedding))
        else:
            existing.model = model
            existing.embedding = embedding

    async def update_settings(
        self,
        collection: Collection,
        *,
        chunking_strategy: str | None,
        chunk_size: int | None,
        chunk_overlap: int | None,
        embedding_model: str | None,
        instructions: dict[str, str] | None,
        generation_models: dict[str, str | None] | None,
        pipeline_windows: dict[str, int] | None,
    ) -> bool:
        """Returns whether the embedding model actually changed - the caller
        uses that to flip reindex_required."""
        settings = collection.settings
        embedding_model_changed = embedding_model is not None and embedding_model != settings.embedding_model

        if chunking_strategy is not None:
            settings.chunking_strategy = chunking_strategy
        if chunk_size is not None:
            settings.chunk_size = chunk_size
        if chunk_overlap is not None:
            settings.chunk_overlap = chunk_overlap
        if embedding_model is not None:
            settings.embedding_model = embedding_model
        if embedding_model_changed:
            settings.reindex_required = True
        if instructions is not None:
            settings.instructions_qa = instructions["qa"]
            settings.instructions_extraction = instructions["extraction"]
            settings.instructions_chunking = instructions["chunking"]
            settings.instructions_tagging = instructions["tagging"]
            settings.instructions_summary = instructions["summary"]
        if generation_models is not None:
            settings.generation_models = {**(settings.generation_models or {}), **generation_models}
        if pipeline_windows is not None:
            settings.pipeline_windows = {**(settings.pipeline_windows or {}), **pipeline_windows}

        return embedding_model_changed

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
