import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import Chunk
from app.models.collection import Collection
from app.models.document import Document, DocumentKind, DocumentPage, DocumentStatus, DocumentType
from app.models.group import ResourceSource
from app.schemas.document_sync import DocumentSyncIn


class CollectionNotSyncedError(Exception):
    """The file belongs to a collection Muffin has no copy of (yet): the collections go first."""


@dataclass(frozen=True)
class DocumentSyncResult:
    document: Document
    created: bool
    chunks_written: int
    chunks_removed: int


class DocumentSyncRepository:
    """The files copied from another system (#453): the row, its text on one page, and the chunks that system made.
    The file itself stays in the other system's bucket, and its vectors in the other system's collection."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sync(self, source: ResourceSource, external_id: str, data: DocumentSyncIn) -> DocumentSyncResult:
        collection_id = await self.db.scalar(
            select(Collection.id).where(
                Collection.source == source, Collection.external_id == data.collection_external_id
            )
        )
        if collection_id is None:
            raise CollectionNotSyncedError(data.collection_external_id)

        document = await self.db.scalar(
            select(Document).where(Document.source == source, Document.external_id == external_id)
        )
        created = document is None
        if document is None:
            document = Document(
                collection_id=collection_id,
                source=source,
                external_id=external_id,
                type=DocumentType.FILE,
                kind=DocumentKind.STANDARD,
                name=data.name,
                storage_key=data.storage_key,
                status=DocumentStatus.INDEXED,
                progress=100,
                content_hash=data.content_hash,
                added_by_user_id=data.added_by_user_id,
                added_by_display=data.added_by_display,
            )
            self.db.add(document)
            await self.db.flush()
        else:
            document.collection_id = collection_id
            document.name, document.storage_key, document.content_hash = data.name, data.storage_key, data.content_hash
            document.added_by_user_id, document.added_by_display = data.added_by_user_id, data.added_by_display
            document.status, document.progress, document.error = DocumentStatus.INDEXED, 100, None

        await self._write_page(document.id, data.text)
        written, removed = await self._write_chunks(document.id, data)
        return DocumentSyncResult(document, created, written, removed)

    async def _write_page(self, document_id: uuid.UUID, text: str) -> None:
        await self.db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        if text:
            self.db.add(DocumentPage(document_id=document_id, page_number=1, content=text))
        await self.db.flush()

    async def _write_chunks(self, document_id: uuid.UUID, data: DocumentSyncIn) -> tuple[int, int]:
        wanted = {chunk.id for chunk in data.chunks}
        current = set(await self.db.scalars(select(Chunk.id).where(Chunk.document_id == document_id)))
        stale = current - wanted
        if stale:
            # First: a stale chunk can hold the position a new one takes.
            await self.db.execute(delete(Chunk).where(Chunk.id.in_(stale)))
        if data.chunks:
            statement = insert(Chunk).values(
                [
                    {
                        "id": chunk.id,
                        "document_id": document_id,
                        "index": chunk.index,
                        "text": chunk.text,
                        "token_count": chunk.token_count,
                    }
                    for chunk in data.chunks
                ]
            )
            await self.db.execute(
                statement.on_conflict_do_update(
                    index_elements=[Chunk.id],
                    set_={
                        "index": statement.excluded.index,
                        "text": statement.excluded.text,
                        "token_count": statement.excluded.token_count,
                    },
                )
            )
        return len(data.chunks), len(stale)

    async def external_ids(self, source: ResourceSource) -> list[str]:
        result = await self.db.scalars(
            select(Document.external_id).where(Document.source == source, Document.external_id.is_not(None))
        )
        return list(result)

    async def delete(self, source: ResourceSource, external_id: str) -> bool:
        """Drops the copy of a file that is gone from the other system, with its page and chunks (cascade)."""
        document = await self.db.scalar(
            select(Document).where(Document.source == source, Document.external_id == external_id)
        )
        if document is None:
            return False
        await self.db.delete(document)
        await self.db.flush()
        return True
