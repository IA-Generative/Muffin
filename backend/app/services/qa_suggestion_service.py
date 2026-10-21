import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext
from app.models.message import MessageRole
from app.models.qa import QaPair
from app.models.run import RunStatus
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.repositories.run_repository import RunRepository
from app.repositories.source_repository import SourceRepository
from app.schemas.qa_suggestion import QaAnswerOut, QaSuggestionOut
from app.services.conversation_service import ConversationNotFoundError
from app.services.qa_source import ensure_source

SUGGESTION_COUNT = 3


class QaPairNotSuggestibleError(Exception):
    """The pair doesn't exist, has no document to cite, or isn't in a collection the user can read."""


class QaSuggestionService:
    """Starter questions for an empty chat, drawn from the question/answer pairs of the collections the
    user can read (#126), and their answer: shown as it is stored, with its source, without asking the
    LLM anything - the pair already is a question with its answer, and the document it came from."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.hierarchy = CollectionHierarchyRepository(db)
        self.qa_pairs = QaPairRepository(db)
        self.conversations = ConversationRepository(db)
        self.runs = RunRepository(db)
        self.sources = SourceRepository(db)

    async def _scope(self, user: RequestContext, pinned_ids: list[uuid.UUID] | None) -> list[uuid.UUID]:
        readable = await self.collections.accessible_ids(user.user_id, user.groups)
        if not pinned_ids:
            return list(readable)
        # What the user pinned in the composer, with what is below it - as a pinned collection is searched.
        wanted = set(await self.hierarchy.subtree_ids(pinned_ids))
        return list(wanted & readable)

    async def suggest(
        self, user: RequestContext, pinned_ids: list[uuid.UUID] | None = None, limit: int = SUGGESTION_COUNT
    ) -> list[QaSuggestionOut]:
        scope = await self._scope(user, pinned_ids)
        # The reviewed pairs first; the generated ones only fill what is left.
        picked = list(await self.qa_pairs.random_with_source(scope, validated=True, limit=limit, exclude=[]))
        if len(picked) < limit:
            picked += await self.qa_pairs.random_with_source(
                scope, validated=False, limit=limit - len(picked), exclude=[pair.id for pair in picked]
            )
        names = await self.hierarchy.names(list({pair.collection_id for pair in picked}))
        return [
            QaSuggestionOut(
                id=pair.id,
                question=pair.question,
                collection_id=pair.collection_id,
                collection_name=names[pair.collection_id].name if pair.collection_id in names else "",
            )
            for pair in picked
        ]

    async def answer(
        self, user: RequestContext, qa_pair_id: uuid.UUID, conversation_id: uuid.UUID | None = None
    ) -> QaAnswerOut:
        pair = await self.qa_pairs.get_with_document(qa_pair_id)
        if pair is None or pair.document is None:
            raise QaPairNotSuggestibleError(str(qa_pair_id))
        if pair.collection_id not in await self.collections.accessible_ids(user.user_id, user.groups):
            raise QaPairNotSuggestibleError(str(qa_pair_id))

        if conversation_id is not None:
            conversation = await self.conversations.get(conversation_id, user.user_id)
            if conversation is None:
                raise ConversationNotFoundError(str(conversation_id))
        else:
            conversation = await self.conversations.create(user.user_id, title=pair.question[:80])

        await ensure_source(self.db, pair)
        question_message = await self.conversations.add_message(conversation.id, MessageRole.USER, pair.question)
        # A finished run with no task behind it: citations live on the run, which is what the history
        # reads them from, so the source stays attached to the answer after a reload.
        run = await self.runs.create(
            user.user_id, pair.question, question_message.id, conversation.id, [pair.collection_id], user.groups
        )
        run.status = RunStatus.COMPLETED
        # Its own transaction: the history orders messages by creation time, which Postgres takes from
        # the start of the transaction - the answer must come after the question, not at the same instant.
        await self.db.commit()
        answer = await self.conversations.add_message(
            conversation.id,
            MessageRole.ASSISTANT,
            f"{pair.answer} [{pair.id}]",
            run_id=run.id,
        )
        citations = await self.sources.link_citations(answer.id, [await self._citation(user, pair)])
        await self.runs.set_result(run, answer.content, citations)
        await self.db.commit()
        return QaAnswerOut(conversation_id=conversation.id, run_id=run.id)

    async def _citation(self, user: RequestContext, pair: QaPair) -> dict[str, Any]:
        # The path from the root down to the collection, through the collections the user can read only.
        own = await self.hierarchy.names([pair.collection_id])
        chains = await self.hierarchy.ancestor_chains([pair.collection_id])
        chain = [own[pair.collection_id], *chains.get(pair.collection_id, [])] if pair.collection_id in own else []
        readable = await self.collections.filter_accessible_ids([item.id for item in chain], user.user_id, user.groups)
        path = [item.name for item in reversed(chain) if item.id in readable]
        return {
            "evidence_id": str(pair.id),
            "source": pair.document.name,
            "vdb_id": str(pair.collection_id),
            "vdb_path": path,
            "tool": "search",
            "evidence_kind": "document",
            "document_id": str(pair.document_id),
            "chunk_id": str(pair.source_chunk_id) if pair.source_chunk_id else None,
            "page_number": pair.source_page,
            "url": None,
            "query": pair.question,
            "content": pair.source_excerpt,
        }
