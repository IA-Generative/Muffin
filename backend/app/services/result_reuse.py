import uuid
from collections.abc import Callable, Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.document import Document
from app.models.document_stage import PipelineStage
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.document_stage_repository import WHOLE, DocumentStageRepository, StageProgress
from app.repositories.entity_repository import EntityRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.services import vector_store
from app.services.document_derived_data import DocumentDerivedData, GeneratedQaPair
from app.services.document_service import DocumentNotFoundError
from app.services.search_service import embed_text

# Undoes, on the way back, what a copy did outside the database: the objects and vectors it wrote.
Undo = list[Callable[[], None]]


class ResultReuse:
    """What the pipeline computes for a file is not computed again for the same file (#300).

    The worker tells, before it computes a stage, the fingerprint of that stage - the hash of the file
    and the settings the stage depends on. If another document of the same file, in any collection,
    completed the stage under the same fingerprint, its results are copied here instead, and the worker
    skips the work: the OCR, the embeddings, the LLM calls. Otherwise the worker computes the stage and
    says when it is done, which is what makes it a source for the next document.

    Nothing here is shown to a user: which document a result came from, and so which collection, never
    leaves the backend. A copy is complete and independent - it owns its screenshots, chunks and
    vectors - so deleting its source leaves it as it is."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.documents = DocumentRepository(db)
        self.stages = DocumentStageRepository(db)
        self.collections = CollectionRepository(db)
        self.qa_pairs = QaPairRepository(db)
        self.entities = EntityRepository(db)
        self.derived = DocumentDerivedData(db)

    async def begin(
        self,
        document_id: uuid.UUID,
        stage: PipelineStage,
        fingerprint: str,
        expected: Sequence[str] = (),
        content_hash: str | None = None,
    ) -> bool:
        """Starts a stage for a document. True: it was copied from another document and is complete, the
        worker has nothing to compute. False: the worker computes it - also when a copy was started and
        failed, which leaves nothing behind. `expected` are the pieces of a stage run in pieces (the
        windows of pages), which complete it when all are done; `content_hash` is the file's hash when
        the worker is the one that knows it (a file hashed lazily, a URL)."""
        document = await self.documents.get(document_id)
        if document is None:
            raise DocumentNotFoundError(str(document_id))
        if content_hash and document.content_hash != content_hash:
            document.content_hash = content_hash
        row = await self.stages.begin(document_id, stage.value, fingerprint, list(expected))
        await self.db.commit()
        if not document.content_hash:
            return False
        source = await self.stages.find_source(stage.value, fingerprint, document.content_hash, document_id)
        if source is None:
            return False
        undo: Undo = []
        try:
            await self._copiers()[stage](source, document, undo)
            await self.stages.complete(row, source.id)
            await self.db.commit()
        except Exception:
            logger.exception(f"Could not reuse the {stage.value} of document {source.id} for {document_id}")
            await self.db.rollback()
            for action in reversed(undo):
                try:
                    action()
                except Exception:
                    logger.exception("Could not undo part of a failed reuse")
            return False
        logger.info(f"Reused the {stage.value} of document {source.id} for document {document_id}")
        return True

    async def mark_done(self, document_id: uuid.UUID, stage: PipelineStage, key: str = WHOLE) -> StageProgress:
        progress = await self.stages.mark_done(document_id, stage.value, key)
        await self.db.commit()
        return progress

    # -- what each stage copies ---------------------------------------------------------------------

    def _copiers(self):
        return {
            PipelineStage.EXTRACTION: self._copy_extraction,
            PipelineStage.CHUNKS: self._copy_chunks,
            PipelineStage.SUMMARY: self._copy_summary,
            PipelineStage.QA: self._copy_qa,
            PipelineStage.ENTITIES: self._copy_entities,
            PipelineStage.TAGS: self._copy_tags,
        }

    async def _copy_extraction(self, source: Document, target: Document, undo: Undo) -> None:
        """The pages, and a copy of each screenshot under the target's own key."""
        copied: list[str] = []
        undo.append(lambda: storage.delete_objects(copied))
        pages = await self.documents.list_pages(source.id)
        for page in pages:
            key = None
            if page.screenshot:
                key = f"screenshots/{target.id}/page-{page.page_number}.png"
                storage.copy_object(page.screenshot, key)
                copied.append(key)
            await self.documents.add_page(target.id, page.page_number, page.content, key)
        await self.documents.prune_pages(target.id, keep=max((page.page_number for page in pages), default=0))

    async def _copy_chunks(self, source: Document, target: Document, undo: Undo) -> None:
        """The chunks - with new ids - and their vectors, read from the source's index and written to the
        target's without embedding anything again."""
        chunks = await self.documents.list_chunks(source.id)
        copies = [
            (
                chunk.id,
                await self.documents.add_chunk(target.id, chunk.index, chunk.text, chunk.token_count, chunk.extras),
            )
            for chunk in chunks
        ]
        await self.documents.prune_chunks(target.id, keep=len(chunks))
        await self.db.flush()
        await self._copy_vectors(
            source.collection_id,
            target.collection_id,
            vector_store.KIND_CHUNK,
            [(old, new.id, new.text) for old, new in copies],
            undo,
        )

    async def _copy_summary(self, source: Document, target: Document, undo: Undo) -> None:
        if not source.summary:
            raise ValueError(f"document {source.id} has no summary to copy")
        await self.documents.set_summary(target, source.summary)
        await self._copy_vectors(
            source.collection_id,
            target.collection_id,
            vector_store.KIND_SUMMARY,
            [(source.id, target.id, source.summary)],
            undo,
        )

    async def _copy_qa(self, source: Document, target: Document, undo: Undo) -> None:
        """The pairs the pipeline generated, not the ones a person validated or wrote - those belong to the
        source's collection. Replaced by window, like a run of the pipeline would, so that a copy can be
        done again."""
        pairs = await self.qa_pairs.list_generated_windows(source.id)
        vectors = vector_store.read_vectors(source.collection_id, [pair.id for pair in pairs])
        by_window: dict[str, list[GeneratedQaPair]] = {}
        for pair in pairs:
            embedding, model = vectors.get(pair.id, (None, None))
            by_window.setdefault(pair.generation_key, []).append(
                GeneratedQaPair(
                    question=pair.question,
                    answer=pair.answer,
                    embedding=embedding,
                    embedding_model=model,
                    source_page=pair.source_page,
                    source_excerpt=pair.source_excerpt,
                )
            )
        for window, generated in by_window.items():
            await self.derived.replace_generated_qa(target.collection_id, target.id, window, generated)

    async def _copy_entities(self, source: Document, target: Document, undo: Undo) -> None:
        for window, (entities, relations) in (await self.entities.export_windows(source.id)).items():
            await self.derived.replace_entity_window(target.collection_id, target.id, window, entities, relations)

    async def _copy_tags(self, source: Document, target: Document, undo: Undo) -> None:
        await self.documents.replace_tags(target, await self.documents.list_tags(source.id))

    async def _copy_vectors(
        self,
        source_collection_id: uuid.UUID,
        target_collection_id: uuid.UUID,
        kind: str,
        points: Sequence[tuple[uuid.UUID, uuid.UUID, str]],
        undo: Undo,
    ) -> None:
        """Writes to the target's index the vectors of the source's points, as (source id, new id, text).
        A vector made with another model than the target's index - the source's collection uses another
        one, or was rebuilt with it - is made again from its text: an index never mixes two models. A point
        with no vector at the source (its embedding had failed) has none here either."""
        vectors = vector_store.read_vectors(source_collection_id, [old for old, _, _ in points])
        active = (await self.collections.get_embedding_models([target_collection_id]))[target_collection_id]
        written: list[tuple[str, uuid.UUID, str, list[float]]] = []
        for old, new, text in points:
            if old not in vectors:
                continue
            embedding, model = vectors[old]
            if model is not None and model != active:
                embedding = await embed_text(active, text)
            written.append((kind, new, text, embedding))
        if not written:
            return
        undo.append(
            lambda: vector_store.delete_points(
                target_collection_id, [str(new) for _, new, _, _ in written], next_index=False
            )
        )
        vector_store.upsert_points(target_collection_id, written, active, next_index=False)
