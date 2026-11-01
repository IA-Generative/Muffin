"""Finding an assistant by what it says it does (#531), with as few calls as it takes.

By default the search runs over **every assistant the person may read** - theirs, those shared with them, the public
ones - and never over one they may not: the candidates come from the same barrier as the list (`AssistantRepository`),
and the search only ranks inside them.

What it costs, on purpose:
- **A handful of assistants needs no vector.** Below `ASSISTANTS_SEARCH_INDEX_MIN` candidates they are matched on their
  words, here, with no call to a model nor to the index.
- **Nothing is written when an assistant changes.** Its point is written when a search finds it missing or out of date
  (hash of its text, embedding model), for all of those at once in one batched embedding call.
- **The question is embedded once**, however many indexes it is searched in (see `embed_query`).
- **No language model is ever asked.** Not to search, not to suggest, not to pick whom to consult."""

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AssistantSettings
from app.core.security.factory import RequestContext
from app.models.assistant import Assistant
from app.repositories.assistant_repository import AssistantRepository
from app.services import search_service, vector_store
from app.services.embedding_model_lookup import default_embedding_model

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = AssistantSettings()

_MAX_TEXT_CHARS = 2000
_WORD = re.compile(r"[a-z0-9]{2,}")

HYBRID = "hybrid"
LEXICAL = "lexical"
# A lexical score is the share of the question's words found in the assistant: this much is "it talks about it".
_LEXICAL_MIN_SCORE = 0.5


@dataclass(frozen=True)
class AssistantHit:
    assistant: Assistant
    # The cosine between the question and the assistant's description (kind `hybrid`), or the share of the question's
    # words the assistant's text holds (kind `lexical`): the two are not compared with each other.
    score: float
    kind: str


def indexed_text(assistant: Assistant) -> str:
    """What the assistant says of itself, and nothing else: the name, the description and the suggested questions - what
    anyone who may read the assistant is shown. Never its instructions, which the author may hide, nor the names of its
    collections, which not every reader may know."""
    return "\n".join([assistant.name, assistant.description, *assistant.suggestions])[:_MAX_TEXT_CHARS]


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    return set(_WORD.findall("".join(char for char in folded if not unicodedata.combining(char))))


def lexical_score(question_words: set[str], assistant: Assistant) -> float:
    """The share of the question's words that start a word of the assistant's text (so that "congé" finds "congés")."""
    if not question_words:
        return 0.0
    own = _words(indexed_text(assistant))
    found = sum(any(word.startswith(wanted) or wanted.startswith(word) for word in own) for wanted in question_words)
    return found / len(question_words)


class AssistantSearchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.assistants = AssistantRepository(db)

    async def readable(self, user: RequestContext) -> list[Assistant]:
        return [assistant for assistant, _writable in await self.assistants.list_accessible(user.user_id, user.groups)]

    async def search(
        self, user: RequestContext, query: str, limit: int | None = None, *, among: list[Assistant] | None = None
    ) -> list[AssistantHit]:
        """The assistants closest to the query, best first - among the ones given, or by default every one the person
        may read. Empty for an empty query: there is nothing to rank by, and the caller lists them by name."""
        candidates = among if among is not None else await self.readable(user)
        return await self.rank(candidates, query, limit)

    async def rank(self, candidates: list[Assistant], query: str, limit: int | None = None) -> list[AssistantHit]:
        query = query.strip()
        limit = min(limit or _settings.ASSISTANTS_SEARCH_LIMIT, _settings.ASSISTANTS_SEARCH_LIMIT)
        if not query or not candidates:
            return []
        if len(candidates) >= _settings.ASSISTANTS_SEARCH_INDEX_MIN:
            try:
                hits = await self._hybrid(candidates, query, limit)
                if hits is not None:
                    return hits
            except Exception:
                # The embedding model or the index is out: the search goes on with the words, and says so in the log.
                logger.warning("The hybrid search of assistants failed, matching their words instead", exc_info=True)
        return self._lexical(candidates, query, limit)

    def _lexical(self, candidates: list[Assistant], query: str, limit: int) -> list[AssistantHit]:
        words = _words(query)
        scored = [(lexical_score(words, assistant), assistant) for assistant in candidates]
        found = [AssistantHit(assistant, score, LEXICAL) for score, assistant in scored if score > 0]
        return sorted(found, key=lambda hit: (-hit.score, hit.assistant.name.lower()))[:limit]

    async def _hybrid(self, candidates: list[Assistant], query: str, limit: int) -> list[AssistantHit] | None:
        model = await default_embedding_model(self.db)
        if model is None or search_service._openai_client is None:
            return None
        await self._ensure_points(candidates, model)
        embedding = await search_service.embed_query(model, query)
        by_id = {assistant.id: assistant for assistant in candidates}
        found = vector_store.search_assistants(query, embedding, list(by_id), limit)
        return [
            AssistantHit(by_id[assistant_id], score, HYBRID) for assistant_id, score in found if assistant_id in by_id
        ]

    async def _ensure_points(self, candidates: list[Assistant], model: str) -> None:
        """Writes the points that are missing or out of date: one read of the index, then one batched embedding call
        and one write for all of them. Nothing is called when every point is current, which is most searches."""
        wanted = {
            assistant.id: (text, hashlib.sha256(text.encode()).hexdigest())
            for assistant in candidates
            if (text := indexed_text(assistant))
        }
        held = vector_store.get_assistant_points(list(wanted))
        stale = [(aid, text, digest) for aid, (text, digest) in wanted.items() if held.get(aid) != (digest, model)]
        if not stale:
            return
        embeddings = await search_service.embed_texts(model, [text for _aid, text, _digest in stale])
        vector_store.upsert_assistants(
            [(aid, text, digest, embedding) for (aid, text, digest), embedding in zip(stale, embeddings, strict=True)],
            model,
        )

    async def index(self, assistant: Assistant) -> None:
        """Embeds what an assistant says of itself when it is made or when that changes: the description is written to
        the index as it is written, not when someone first searches. Best effort: an embedding model or an index that
        is down costs only this, the next search writes the point (`_ensure_points`). It calls the embedding model only
        when the text or the model is not the one the point was made with."""
        try:
            model = await default_embedding_model(self.db)
            if model is not None and search_service._openai_client is not None:
                await self._ensure_points([assistant], model)
        except Exception:
            logger.warning(f"Could not index assistant {assistant.id}, a search will", exc_info=True)

    async def suggest(self, user: RequestContext, question: str, limit: int = 3) -> list[AssistantHit]:
        """The assistants whose description fits a question well enough to be proposed - possibly none. Proposed only:
        nothing here applies an assistant."""
        hits = await self.search(user, question, limit)
        return [
            hit
            for hit in hits
            if hit.score >= (_settings.ASSISTANTS_SUGGEST_MIN_SCORE if hit.kind == HYBRID else _LEXICAL_MIN_SCORE)
        ]

    async def closest(self, candidates: list[Assistant], question: str, maximum: int) -> list[Assistant]:
        """Which of these assistants to keep for a question: all of them when there are `maximum` or fewer - no search,
        no call - and otherwise the closest ones."""
        if len(candidates) <= maximum:
            return list(candidates)
        return [hit.assistant for hit in await self.rank(candidates, question, maximum)]


def forget(assistant_id: uuid.UUID) -> None:
    """Takes an assistant that was deleted out of the index (an orphan would never be returned, the candidates being
    filtered first, but it would stay there)."""
    vector_store.delete_assistant_point(assistant_id)
