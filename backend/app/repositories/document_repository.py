import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentPage, DocumentStatus, DocumentType


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def get_in_collection(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(
            select(Document).where(Document.id == document_id, Document.collection_id == collection_id)
        )
        return result.scalar_one_or_none()

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[Document]:
        result = await self.db.execute(
            select(Document).where(Document.collection_id == collection_id).order_by(Document.created_at)
        )
        return result.scalars().all()

    async def create_file(self, collection_id: uuid.UUID, name: str, storage_key: str) -> Document:
        document = Document(collection_id=collection_id, name=name, type=DocumentType.FILE, storage_key=storage_key)
        self.db.add(document)
        await self.db.flush()
        return document

    async def create_url(self, collection_id: uuid.UUID, url: str) -> Document:
        document = Document(collection_id=collection_id, name=url, type=DocumentType.URL)
        self.db.add(document)
        await self.db.flush()
        return document

    async def list_rustfs_keys_for_document(self, document_id: uuid.UUID) -> list[str]:
        document = await self.get(document_id)
        keys = [document.storage_key] if document and document.storage_key else []
        screenshots = await self.db.scalars(
            select(DocumentPage.screenshot).where(
                DocumentPage.document_id == document_id, DocumentPage.screenshot.is_not(None)
            )
        )
        keys.extend(screenshots.all())
        return keys

    async def delete(self, document: Document) -> None:
        await self.db.delete(document)

    async def clear_content(self, document_id: uuid.UUID) -> list[str]:
        """Wipes this document's pages/chunks before reprocessing - add_page/
        add_chunk are pure inserts, so without this a reindex would duplicate
        content instead of replacing it. Returns the screenshot keys being
        cleared, so the caller can delete those now-orphaned RustFS objects."""
        screenshots = await self.db.scalars(
            select(DocumentPage.screenshot).where(
                DocumentPage.document_id == document_id, DocumentPage.screenshot.is_not(None)
            )
        )
        keys = list(screenshots.all())
        await self.db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        await self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        return keys

    async def update_status(
        self, document: Document, status: DocumentStatus, progress: int | None, summary: str | None
    ) -> None:
        document.status = status
        if progress is not None:
            document.progress = progress
        if summary is not None:
            document.summary = summary

    async def add_page(
        self, document_id: uuid.UUID, page_number: int, content: str, screenshot: str | None
    ) -> DocumentPage:
        page = DocumentPage(document_id=document_id, page_number=page_number, content=content, screenshot=screenshot)
        self.db.add(page)
        await self.db.flush()
        return page

    async def add_chunk(
        self, document_id: uuid.UUID, index: int, text: str, token_count: int, extras: dict[str, Any] | None
    ) -> Chunk:
        chunk = Chunk(document_id=document_id, index=index, text=text, token_count=token_count, extras=extras)
        self.db.add(chunk)
        await self.db.flush()
        return chunk
