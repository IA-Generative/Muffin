import uuid

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.repositories.collection_repository import CollectionRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.schemas.collection import QaPairCreate, QaPairOut, RelevantDocumentOut
from app.services import vector_store
from app.services.collection_service import CollectionNotFoundError
from app.services.search_service import embed_text


class QaPairNotFoundError(Exception):
    pass


class UnknownDocumentError(Exception):
    """A relevant document that isn't in this collection."""


class TooManyDocumentsError(Exception):
    """A reference pair has one source document; only a golden pair can name several."""


class GoldenPairNotValidatableError(Exception):
    """A golden pair is validated by definition - its validation can't be toggled."""


class QaPairService:
    """What the owner of a collection does to its question/answer pairs: write a reference pair or a
    test (golden) question (#260), remove a pair, validate or unvalidate a generated one. Generated
    pairs are still created by the document pipeline, never here."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.qa_pairs = QaPairRepository(db)

    async def create(self, collection_id: uuid.UUID, user: RequestContext, body: QaPairCreate) -> QaPairOut:
        await self._owned(collection_id, user)
        # A relevant document is only one this collection really has, in the order given, once each.
        document_ids = list(dict.fromkeys(body.relevant_document_ids))
        if len(document_ids) > 1 and not body.golden:
            raise TooManyDocumentsError(str(collection_id))
        names = await self.qa_pairs.document_names(collection_id, document_ids)
        if any(str(document_id) not in names for document_id in document_ids):
            raise UnknownDocumentError(str(collection_id))
        pair = await self.qa_pairs.create_manual(
            collection_id, body.question, body.answer, document_ids, golden=body.golden
        )
        await self.db.commit()
        # A golden pair is deliberately never embedded: nothing in the retriever may match it. A
        # reference pair is, so the assistant can answer from it before searching.
        if not body.golden:
            await self._embed(collection_id, pair.id, body.question, pair.document_id)
        return QaPairOut(
            id=pair.id,
            question=pair.question,
            answer=pair.answer,
            source=names[str(document_ids[0])] if document_ids else None,
            origin=pair.origin,
            validated=pair.validated,
            golden=pair.golden,
            relevant_documents=[
                RelevantDocumentOut(id=document_id, name=names[str(document_id)]) for document_id in document_ids
            ],
        )

    async def _embed(
        self, collection_id: uuid.UUID, qa_pair_id: uuid.UUID, question: str, document_id: uuid.UUID | None
    ) -> None:
        """Best-effort, like the pipeline's own embedding of a generated pair: a pair that couldn't be
        embedded still exists and shows in the list, it just isn't matched by the assistant."""
        try:
            model = (await self.collections.get_embedding_models([collection_id]))[collection_id]
            vector_store.upsert_qa_embedding(
                collection_id, qa_pair_id, await embed_text(model, question), question, model, document_id
            )
        except Exception:
            logger.exception(f"Failed to embed the manual QA pair {qa_pair_id}")

    async def delete(self, collection_id: uuid.UUID, user: RequestContext, qa_pair_id: uuid.UUID) -> None:
        await self._owned(collection_id, user)
        pair = await self._pair(collection_id, qa_pair_id)
        golden = pair.golden
        await self.qa_pairs.delete(pair)
        await self.db.commit()
        if not golden:
            vector_store.delete_qa_embedding(collection_id, qa_pair_id)

    async def set_validated(
        self, collection_id: uuid.UUID, user: RequestContext, qa_pair_id: uuid.UUID, validated: bool
    ) -> None:
        await self._owned(collection_id, user)
        pair = await self._pair(collection_id, qa_pair_id)
        if pair.golden:
            raise GoldenPairNotValidatableError(str(qa_pair_id))
        pair.validated = validated
        await self.db.commit()

    async def _owned(self, collection_id: uuid.UUID, user: RequestContext) -> None:
        if await self.collections.get(collection_id, user.user_id) is None:
            raise CollectionNotFoundError(str(collection_id))

    async def _pair(self, collection_id: uuid.UUID, qa_pair_id: uuid.UUID):  # noqa: ANN202
        pair = await self.qa_pairs.get_in_collection(collection_id, qa_pair_id)
        if pair is None:
            raise QaPairNotFoundError(str(qa_pair_id))
        return pair
