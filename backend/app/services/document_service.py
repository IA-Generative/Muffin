import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentPage, DocumentStatus
from app.models.document_tabular_profile import DocumentTabularProfile
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.schemas.internal_document import (
    ChunkCreate,
    DocumentPageCreate,
    DocumentStatusUpdate,
)
from app.schemas.internal_pipeline import TabularProfileCreate
from app.services import vector_store
from app.services.embedding_model_lookup import default_embedding_model
from app.services.search_service import embed_text


class DocumentNotFoundError(Exception):
    pass


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = DocumentRepository(db)
        self.collections = CollectionRepository(db)

    async def get_document(self, document_id: uuid.UUID) -> Document:
        document = await self.repository.get(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        return document

    async def update_status(self, document_id: uuid.UUID, update: DocumentStatusUpdate) -> Document:
        document = await self.get_document(document_id)
        await self.repository.update_status(document, DocumentStatus(update.status), update.progress, update.summary)
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def list_pages(self, document_id: uuid.UUID) -> list[DocumentPage]:
        await self.get_document(document_id)
        return list(await self.repository.list_pages(document_id))

    async def add_page(self, document_id: uuid.UUID, page: DocumentPageCreate) -> DocumentPage:
        await self.get_document(document_id)
        created = await self.repository.add_page(document_id, page.page_number, page.content, page.screenshot)
        await self.db.commit()
        return created

    async def add_chunk(self, document_id: uuid.UUID, chunk: ChunkCreate) -> Chunk:
        document = await self.get_document(document_id)
        created = await self.repository.add_chunk(document_id, chunk.index, chunk.text, chunk.token_count, chunk.extras)
        await self.db.commit()
        if chunk.embedding is not None:
            vector_store.upsert_chunk_embedding(document.collection_id, created.id, chunk.embedding, chunk.text)
        return created

    async def set_summary(self, document_id: uuid.UUID, summary: str, embedding: list[float] | None = None) -> None:
        document = await self.get_document(document_id)
        await self.repository.set_summary(document, summary)
        await self.db.commit()
        if embedding is not None:
            vector_store.upsert_summary_embedding(document.collection_id, document.id, embedding, summary)

    async def set_error(self, document_id: uuid.UUID, error: str) -> None:
        document = await self.get_document(document_id)
        await self.repository.set_error(document, error)
        await self.db.commit()

    async def set_tabular_profile(
        self, document_id: uuid.UUID, profile: TabularProfileCreate
    ) -> DocumentTabularProfile:
        await self.get_document(document_id)
        created = await self.repository.upsert_tabular_profile(
            document_id=document_id,
            row_count=profile.row_count,
            column_count=profile.column_count,
            format_=profile.format,
            columns=[col.model_dump() for col in profile.columns],
            sample_rows=profile.sample_rows,
            measures=profile.measures,
            dimensions=profile.dimensions,
            text_columns=profile.text_columns,
        )
        await self.db.commit()
        await self.db.refresh(created)
        return created

    async def get_tabular_profile(self, document_id: uuid.UUID) -> DocumentTabularProfile | None:
        await self.get_document(document_id)
        return await self.repository.get_tabular_profile(document_id)

    async def replace_tags(self, document_id: uuid.UUID, tags: list[str]) -> None:
        document = await self.get_document(document_id)
        await self.repository.replace_tags(document, tags)
        await self.db.commit()

    # How many candidates to keep (§122 follow-up: "avec un topk avec les suggestions") - large
    # enough to give the user a genuine choice when the top match isn't quite right, small enough
    # to stay a short list, not a second collection picker.
    FILING_TOP_K = 5

    async def suggest_filing(self, document_id: uuid.UUID) -> None:
        """Called (best-effort, fire-and-forget) once a conversation file's summary is ready
        (§122) - a no-op for anything but a file sitting in a temporary collection with a
        summary to compare. Embeds the summary with the admin-configured global embedding model
        (never the collection's own chunk embedding_model - it must share the same space as
        every collection description in the "collections" Meilisearch index, §124) and keeps the
        top FILING_TOP_K collections this uploader owns, ranked by similarity."""
        document = await self.repository.get_with_collection(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if not document.collection.is_temporary or not document.summary:
            return

        model = await default_embedding_model(self.db)
        if model is None:
            return
        try:
            embedding = await embed_text(model, document.summary)
        except Exception:
            logger.exception(f"Failed to embed the summary for filing suggestion on document {document_id}")
            return

        owned_ids = await self.collections.list_owned_ids(document.collection.owner_id)
        results = vector_store.search_collections(document.summary, embedding, list(owned_ids), limit=self.FILING_TOP_K)
        if not results:
            return

        collections_by_id = {c.id: c for c in await self.collections.get_by_ids([cid for cid, _ in results])}
        candidates = [
            {
                "collection_id": str(collection_id),
                "collection_name": collections_by_id[collection_id].name,
                # The "why" shown to the user (§122) - the matched collection's own description,
                # not a generated explanation: no extra LLM call, and it's the most direct answer
                # to "why did you suggest this one" there is.
                "collection_description": collections_by_id[collection_id].description,
                "score": score,
            }
            for collection_id, score in results
            if collection_id in collections_by_id  # defensive: deleted between search and here
        ]
        if not candidates:
            return

        await self.repository.set_filing_suggestion(
            document, uuid.UUID(candidates[0]["collection_id"]), candidates[0]["score"]
        )
        await self.repository.set_filing_candidates(document, candidates)
        await self.db.commit()
