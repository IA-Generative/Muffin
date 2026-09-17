import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.document import Document, DocumentPage, DocumentStatus


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

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
