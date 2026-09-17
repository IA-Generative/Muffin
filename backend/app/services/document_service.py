import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentPage, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.schemas.internal_document import ChunkCreate, DocumentPageCreate, DocumentStatusUpdate


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

    async def add_page(self, document_id: uuid.UUID, page: DocumentPageCreate) -> DocumentPage:
        await self.get_document(document_id)
        created = await self.repository.add_page(document_id, page.page_number, page.content, page.screenshot)
        await self.db.commit()
        return created

    async def add_chunk(self, document_id: uuid.UUID, chunk: ChunkCreate) -> Chunk:
        await self.get_document(document_id)
        created = await self.repository.add_chunk(document_id, chunk.index, chunk.text, chunk.token_count, chunk.extras)
        await self.db.commit()
        return created
