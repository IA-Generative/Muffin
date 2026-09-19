import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import MessageSource, Source

# Only these tools produce a citation with a real, stable identity worth persisting as a
# validatable Source - "search"/"page_content" point at a document+chunk, "web_search" at an
# external URL. Everything else (list_collections, collection_summary, list_documents) is a
# meta/knowledge-base lookup with no document/url to attach (see SourcesPanel.vue's "tool" card,
# which has nothing to open either).
_CITABLE_TOOLS = frozenset({"search", "page_content", "web_search"})


class SourceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(
        self,
        title: str,
        url: str | None,
        document_id: uuid.UUID | None,
        chunk_id: uuid.UUID | None,
        page_number: int | None,
    ) -> Source:
        """Dedupes by the same identity a citation actually has - a url for a web source, a
        document+chunk pair for a document one - so the same page cited across many runs/
        conversations doesn't grow the table without bound."""
        if url is not None:
            existing = await self.db.execute(select(Source).where(Source.url == url))
        else:
            existing = await self.db.execute(
                select(Source).where(Source.document_id == document_id, Source.chunk_id == chunk_id)
            )
        source = existing.scalar_one_or_none()
        if source is not None:
            return source

        source = Source(title=title, url=url, document_id=document_id, chunk_id=chunk_id, page_number=page_number)
        self.db.add(source)
        await self.db.flush()
        return source

    async def filter_linked(self, message_id: uuid.UUID, source_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        """Narrows a caller-supplied list of source ids down to the ones actually linked to this
        message (via message_sources) - never trust a "validated_source_ids" a feedback request
        supplies without checking it against what was really cited, same reasoning as every other
        client-supplied id in this codebase."""
        if not source_ids:
            return []
        result = await self.db.execute(
            select(MessageSource.source_id).where(
                MessageSource.message_id == message_id, MessageSource.source_id.in_(source_ids)
            )
        )
        return list(result.scalars().all())

    async def link_citations(self, message_id: uuid.UUID, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Materializes and links every citable citation (see _CITABLE_TOOLS) of a just-persisted
        assistant message - called once, right after ConversationRepository.add_message, from
        PATCH /internal/runs/{id}/result. Returns citations with a `source_id` merged into every
        entry that got materialized, so the caller can store *that* (not the original list) as
        the message's citations - it's what gives the frontend a stable id to send back on
        feedback (see FeedbackSource)."""
        linked_source_ids: set[uuid.UUID] = set()
        enriched = []
        for citation in citations:
            if citation.get("tool") not in _CITABLE_TOOLS:
                enriched.append(citation)
                continue
            url = citation.get("url")
            document_id = uuid.UUID(citation["document_id"]) if citation.get("document_id") else None
            chunk_id = uuid.UUID(citation["chunk_id"]) if citation.get("chunk_id") else None
            if url is None and document_id is None:
                # Neither identity is available - nothing stable to dedupe or link on.
                enriched.append(citation)
                continue

            source = await self.get_or_create(
                title=citation.get("source") or url or "Source",
                url=url,
                document_id=document_id,
                chunk_id=chunk_id,
                page_number=citation.get("page_number"),
            )
            if source.id not in linked_source_ids:
                linked_source_ids.add(source.id)
                self.db.add(MessageSource(message_id=message_id, source_id=source.id))
            enriched.append({**citation, "source_id": str(source.id)})
        await self.db.flush()
        return enriched
