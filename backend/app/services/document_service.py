import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentPage, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.schemas.internal_document import ChunkCreate, DocumentPageCreate, DocumentStatusUpdate
from app.services import vector_store


class DocumentNotFoundError(Exception):
    pass


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repository = DocumentRepository(db)

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

    async def replace_tags(self, document_id: uuid.UUID, tags: list[str]) -> None:
        document = await self.get_document(document_id)
        await self.repository.replace_tags(document, tags)
        await self.db.commit()
