import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chunk import Chunk
from app.models.collection import Collection
from app.models.document import (
    Document,
    DocumentPage,
    DocumentStatus,
    DocumentTag,
    DocumentType,
)
from app.models.document_tabular_profile import DocumentTabularProfile


class DocumentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, document_ids: list[uuid.UUID]) -> Sequence[Document]:
        if not document_ids:
            return []
        result = await self.db.execute(select(Document).where(Document.id.in_(document_ids)))
        return result.scalars().all()

    async def get_with_collection(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(
            select(Document).where(Document.id == document_id).options(selectinload(Document.collection))
        )
        return result.scalar_one_or_none()

    async def get_with_suggestion(self, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.collection), selectinload(Document.suggested_collection))
        )
        return result.scalar_one_or_none()

    async def list_to_file(self, user_id: str) -> Sequence[Document]:
        """Files this user uploaded (§122) that still need filing into a permanent collection:
        still sitting in a temporary (conversation-scoped) collection, or - an edge case worth
        surfacing rather than hiding - ended up in a collection this user no longer owns (e.g.
        ownership changed since). Always includes a dismissed file too (§ Document.
        filing_dismissed only suppresses the chat notification, not this review page - the file
        is still genuinely unfiled either way)."""
        result = await self.db.execute(
            select(Document)
            .join(Document.collection)
            .where(
                Document.added_by_user_id == user_id,
                or_(Collection.is_temporary.is_(True), Collection.owner_id != user_id),
            )
            .options(selectinload(Document.collection), selectinload(Document.suggested_collection))
            .order_by(Document.created_at.desc())
        )
        return result.scalars().all()

    async def get_in_collection(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(
            select(Document).where(Document.id == document_id, Document.collection_id == collection_id)
        )
        return result.scalar_one_or_none()

    async def get_in_collection_with_tags(self, collection_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        result = await self.db.execute(
            select(Document)
            .where(Document.id == document_id, Document.collection_id == collection_id)
            .options(selectinload(Document.tags))
        )
        return result.scalar_one_or_none()

    async def list_pages(self, document_id: uuid.UUID) -> Sequence[DocumentPage]:
        result = await self.db.execute(
            select(DocumentPage).where(DocumentPage.document_id == document_id).order_by(DocumentPage.page_number)
        )
        return result.scalars().all()

    async def list_pages_page(
        self, document_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[DocumentPage], int]:
        total = await self.db.scalar(
            select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == document_id)
        )
        result = await self.db.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total or 0

    async def count_pages(self, document_id: uuid.UUID) -> int:
        return (
            await self.db.scalar(
                select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == document_id)
            )
        ) or 0

    async def get_page(self, document_id: uuid.UUID, page_number: int) -> DocumentPage | None:
        result = await self.db.execute(
            select(DocumentPage).where(
                DocumentPage.document_id == document_id,
                DocumentPage.page_number == page_number,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_collection(self, collection_id: uuid.UUID) -> Sequence[Document]:
        result = await self.db.execute(
            select(Document)
            .where(Document.collection_id == collection_id)
            .options(selectinload(Document.suggested_collection))
            .order_by(Document.created_at)
        )
        return result.scalars().all()

    async def list_summaries_by_collection(self, collection_id: uuid.UUID) -> Sequence[str]:
        result = await self.db.scalars(
            select(Document.summary)
            .where(Document.collection_id == collection_id, Document.summary.is_not(None))
            .order_by(Document.created_at)
        )
        return result.all()

    async def create_file(
        self,
        collection_id: uuid.UUID,
        name: str,
        storage_key: str,
        added_by_user_id: str | None = None,
        added_by_display: str | None = None,
    ) -> Document:
        document = Document(
            collection_id=collection_id,
            name=name,
            type=DocumentType.FILE,
            storage_key=storage_key,
            added_by_user_id=added_by_user_id,
            added_by_display=added_by_display,
        )
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
                DocumentPage.document_id == document_id,
                DocumentPage.screenshot.is_not(None),
            )
        )
        keys.extend(screenshots.all())
        return keys

    async def list_chunk_ids(self, document_id: uuid.UUID) -> list[uuid.UUID]:
        """Returns the chunk ids of a document - needed to delete their Meilisearch embeddings
        alongside the document itself (see vector_store.delete_document_embeddings), before the
        Postgres rows go away and those ids can't be looked up anymore."""
        result = await self.db.scalars(select(Chunk.id).where(Chunk.document_id == document_id))
        return list(result.all())

    async def delete(self, document: Document) -> None:
        await self.db.delete(document)

    async def clear_content(self, document_id: uuid.UUID) -> list[str]:
        """Wipes this document's pages/chunks before reprocessing - add_page/
        add_chunk are pure inserts, so without this a reindex would duplicate
        content instead of replacing it. Returns the screenshot keys being
        cleared, so the caller can delete those now-orphaned RustFS objects."""
        screenshots = await self.db.scalars(
            select(DocumentPage.screenshot).where(
                DocumentPage.document_id == document_id,
                DocumentPage.screenshot.is_not(None),
            )
        )
        keys = list(screenshots.all())
        await self.db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        await self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        return keys

    async def update_status(
        self,
        document: Document,
        status: DocumentStatus,
        progress: int | None,
        summary: str | None,
    ) -> None:
        document.status = status
        if progress is not None:
            document.progress = progress
        if summary is not None:
            document.summary = summary

    async def set_summary(self, document: Document, summary: str) -> None:
        document.summary = summary

    async def set_error(self, document: Document, error: str) -> None:
        document.error = error

    async def set_filing_suggestion(self, document: Document, collection_id: uuid.UUID, score: float) -> None:
        document.suggested_collection_id = collection_id
        document.suggested_collection_score = score

    async def set_filing_candidates(self, document: Document, candidates: list[dict[str, Any]]) -> None:
        document.filing_candidates = candidates

    async def set_filing_dismissed(self, document: Document) -> None:
        document.filing_dismissed = True

    async def move_to_collection(self, document: Document, collection_id: uuid.UUID) -> None:
        """Re-homes a document into a different collection in place - keeps its id stable (so
        anything that already cited it, e.g. a run's citations, keeps resolving) rather than
        deleting and recreating it. Chunks/pages are cleared and its status reset to PENDING;
        the caller is responsible for actually re-enqueueing processing and cleaning up the old
        collection's Meilisearch embeddings, same division of labour as reindex_collection."""
        document.collection_id = collection_id
        document.status = DocumentStatus.PENDING
        document.progress = 0
        document.summary = None

    async def upsert_tabular_profile(
        self,
        document_id: uuid.UUID,
        row_count: int,
        column_count: int,
        format_: str,
        columns: list[dict[str, Any]],
        sample_rows: list[dict[str, Any]],
        measures: list[str] | None = None,
        dimensions: list[str] | None = None,
        text_columns: list[str] | None = None,
    ) -> DocumentTabularProfile:
        """Insert or replace the tabular profile for a document. A reindex
        would call this again with fresh stats - we replace rather than
        error on the unique constraint."""
        existing = await self.db.scalar(
            select(DocumentTabularProfile).where(DocumentTabularProfile.document_id == document_id)
        )
        if existing is not None:
            existing.row_count = row_count
            existing.column_count = column_count
            existing.format = format_
            existing.columns = columns
            existing.sample_rows = sample_rows
            existing.measures = measures or []
            existing.dimensions = dimensions or []
            existing.text_columns = text_columns or []
            return existing
        profile = DocumentTabularProfile(
            document_id=document_id,
            row_count=row_count,
            column_count=column_count,
            format=format_,
            columns=columns,
            sample_rows=sample_rows,
            measures=measures or [],
            dimensions=dimensions or [],
            text_columns=text_columns or [],
        )
        self.db.add(profile)
        await self.db.flush()
        return profile

    async def get_tabular_profile(self, document_id: uuid.UUID) -> DocumentTabularProfile | None:
        result = await self.db.execute(
            select(DocumentTabularProfile).where(DocumentTabularProfile.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def list_tabular_documents(self, collection_id: uuid.UUID) -> list[tuple[Document, DocumentTabularProfile]]:
        """Returns (document, profile) pairs for every document in the collection that has a
        tabular profile - i.e. the ones the research agent can query with DuckDB."""
        result = await self.db.execute(
            select(Document, DocumentTabularProfile)
            .join(
                DocumentTabularProfile,
                DocumentTabularProfile.document_id == Document.id,
            )
            .where(Document.collection_id == collection_id)
            .order_by(Document.created_at)
        )
        return [(doc, profile) for doc, profile in result.all()]

    async def replace_tags(self, document: Document, tags: list[str]) -> None:
        # Adds directly rather than assigning `document.tags = [...]`: that
        # relationship isn't eager-loaded by `get()`, and reassigning it would
        # need SQLAlchemy to lazy-load the current collection first, which
        # can't happen outside a greenlet in async mode.
        await self.db.execute(delete(DocumentTag).where(DocumentTag.document_id == document.id))
        self.db.add_all([DocumentTag(document_id=document.id, tag=tag) for tag in dict.fromkeys(tags)])

    async def add_page(
        self,
        document_id: uuid.UUID,
        page_number: int,
        content: str,
        screenshot: str | None,
    ) -> DocumentPage:
        page = DocumentPage(
            document_id=document_id,
            page_number=page_number,
            content=content,
            screenshot=screenshot,
        )
        self.db.add(page)
        await self.db.flush()
        return page

    async def add_chunk(
        self,
        document_id: uuid.UUID,
        index: int,
        text: str,
        token_count: int,
        extras: dict[str, Any] | None,
    ) -> Chunk:
        chunk = Chunk(
            document_id=document_id,
            index=index,
            text=text,
            token_count=token_count,
            extras=extras,
        )
        self.db.add(chunk)
        await self.db.flush()
        return chunk
