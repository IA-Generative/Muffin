import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.repositories.entity_repository import EntityRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.services import vector_store
from app.services.index_vectors import vector_for_active_index


@dataclass(frozen=True)
class GeneratedQaPair:
    question: str
    answer: str
    embedding: list[float] | None = None
    embedding_model: str | None = None
    source_page: int | None = None
    source_excerpt: str | None = None


class DocumentDerivedData:
    """What the pipeline derives from a document's content - the QA pairs, entities and relations it
    generates (#299). It is written by runs, each replacing what an earlier run of the same scope
    wrote, so a task run twice (a redelivery after a crash) leaves the same state as one run; and it
    goes with the document: removed when the document is deleted, or reprocessed (which regenerates it).
    None of it commits: the caller does, with the rest of its change."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.qa_pairs = QaPairRepository(db)
        self.entities = EntityRepository(db)

    async def replace_generated_qa(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID | None,
        generation_key: str,
        pairs: Sequence[GeneratedQaPair],
    ) -> None:
        """Records the pairs one run generated - a window of a document's pages, a tabular profile, a
        collection's description - in place of what the previous run of the same key had recorded."""
        removed = await self.qa_pairs.delete_generated_run(collection_id, document_id, generation_key)
        vector_store.delete_qa_embeddings(collection_id, removed)
        for pair in pairs:
            created = await self.qa_pairs.create(
                collection_id,
                document_id,
                pair.question,
                pair.answer,
                pair.source_page,
                pair.source_excerpt,
                generation_key,
            )
            if pair.embedding is None:
                continue
            embedding, model = await vector_for_active_index(
                self.db, collection_id, pair.question, pair.embedding, pair.embedding_model
            )
            if embedding is not None:
                vector_store.upsert_qa_embedding(collection_id, created.id, embedding, pair.question, model)

    async def replace_entity_window(
        self,
        collection_id: uuid.UUID,
        document_id: uuid.UUID,
        window_key: str,
        entities: Sequence[tuple[str, str, int]],
        relations: Sequence[tuple[str, str, str]],
    ) -> None:
        """Records the entities and relations extracted from one window of pages, in place of what the
        previous extraction of that window had recorded."""
        await self.entities.replace_window(collection_id, document_id, window_key, entities, relations)

    async def clear(self, document: Document, *, keep_validated_qa: bool) -> None:
        """Removes what was derived from a document. For a reprocess (`keep_validated_qa`: a pair a
        person validated stays) and for a deletion, where nothing is kept - what they answer from is
        gone. The vectors of the pairs are removed before the caller commits, like a document's own (see
        vector_store.delete_document_embeddings): a failure there leaves orphaned vectors, which search
        never returns, never a pair without its row."""
        removed = await self.qa_pairs.delete_generated_for_document(document.id, keep_validated=keep_validated_qa)
        for collection_id in {collection for collection, _ in removed}:
            vector_store.delete_qa_embeddings(
                collection_id, [pair for collection, pair in removed if collection == collection_id]
            )
        await self.entities.remove_document(document.id)
