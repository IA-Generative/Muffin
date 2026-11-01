"""Finding a tool by what it does (#530), with as few calls as it takes.

The search **only ranks**. The caller (`ToolService`) has already kept the tools the person may use - their servers, the
ones shared with them, Muffin's own, not a server that is off or deleted - and this ranks inside that list: it never
widens it, and it never says that a tool it was not given exists.

What it costs, on purpose - the same as for assistants (`AssistantSearchService`):
- **A handful of tools needs no vector.** Below `TOOLS_SEARCH_INDEX_MIN` candidates they are matched on their words,
  with no call to a model nor to the index.
- **A point is written when a search finds it missing or out of date** (hash of its text, embedding model), and when a
  server is synchronised; a tool whose text did not change is never embedded again.
- **The question is embedded once**, however many indexes it is searched in.
- **No language model is ever asked.** The search preselects; the model chooses what to call.

What is indexed is the name, the description and the names of the parameters - bounded: a description is written by a
third party (the server) and read by a model. It is never executed, and never holds an argument, a result or a token."""

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ToolSettings
from app.schemas.tool import ToolOut
from app.services import search_service, vector_store
from app.services.embedding_model_lookup import default_embedding_model

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = ToolSettings()

# A tool's text is cut here: a long description is not a better one, and the more of it is indexed the more a server
# can write to be found for any question.
_MAX_TEXT_CHARS = 1000
_MAX_PARAMETERS = 20

HYBRID = "hybrid"
LEXICAL = "lexical"


@dataclass(frozen=True)
class ToolHit:
    tool: ToolOut
    # The cosine between the question and the tool's description (kind `hybrid`), or the share of the question's words
    # the tool's text holds (kind `lexical`): the two are not compared with each other.
    score: float
    kind: str


def point_id(ref: str) -> uuid.UUID:
    """The id of a tool's point: the tool's own id for a tool of a server, a stable id made of the reference for one of
    Muffin's."""
    try:
        return uuid.UUID(ref)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"muffin:tool:{ref}")


def indexed_text(name: str, description: str, input_schema: dict) -> str:
    """What the tool says of itself: its name, its description and the names of what it takes. Never a value."""
    properties = input_schema.get("properties") if isinstance(input_schema, dict) else None
    parameters = list(properties)[:_MAX_PARAMETERS] if isinstance(properties, dict) else []
    parts = [name.replace("_", " ").replace("-", " "), description]
    if parameters:
        parts.append("Paramètres : " + ", ".join(str(parameter) for parameter in parameters))
    return "\n".join(parts)[:_MAX_TEXT_CHARS]


def _lexical_score(question_terms: set[str], tool: ToolOut) -> float:
    """The share of the question's terms the tool's text holds - the terms of the BM25 branch, so that "devises" finds
    "devise" and "des" finds nothing."""
    if not question_terms:
        return 0.0
    own = vector_store.terms(indexed_text(tool.name, tool.description, tool.input_schema))
    return len(question_terms & own) / len(question_terms)


class ToolSearchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def rank(self, candidates: list[ToolOut], query: str, limit: int | None = None) -> list[ToolHit]:
        """The candidates closest to the query, best first - empty for an empty query, which is not a search (the
        caller lists the tools by name). Never raises: when the embedding model or the index is out, the words are
        matched instead and the log says so."""
        query = query.strip()
        limit = min(limit or _settings.TOOLS_SEARCH_LIMIT, _settings.TOOLS_SEARCH_LIMIT)
        if not query or not candidates:
            return []
        if len(candidates) >= _settings.TOOLS_SEARCH_INDEX_MIN:
            try:
                hits = await self._hybrid(candidates, query, limit)
                if hits is not None:
                    return hits
            except Exception:
                logger.warning("The hybrid search of tools failed, matching their words instead", exc_info=True)
        return self._lexical(candidates, query, limit)

    @staticmethod
    def _lexical(candidates: list[ToolOut], query: str, limit: int) -> list[ToolHit]:
        words = vector_store.terms(query)
        scored = [(_lexical_score(words, tool), tool) for tool in candidates]
        found = [ToolHit(tool, score, LEXICAL) for score, tool in scored if score > 0]
        return sorted(found, key=lambda hit: (-hit.score, hit.tool.name.lower()))[:limit]

    async def _hybrid(self, candidates: list[ToolOut], query: str, limit: int) -> list[ToolHit] | None:
        model = await default_embedding_model(self.db)
        if model is None or search_service._openai_client is None:
            return None
        by_id = {point_id(tool.ref): tool for tool in candidates}
        await self._ensure_points(
            [(point_id(tool.ref), indexed_text(tool.name, tool.description, tool.input_schema)) for tool in candidates],
            model,
        )
        embedding = await search_service.embed_query(model, query)
        found = vector_store.search_tools(query, embedding, list(by_id), limit)
        return [ToolHit(by_id[tool_id], score, HYBRID) for tool_id, score in found if tool_id in by_id]

    @staticmethod
    async def _ensure_points(texts: Iterable[tuple[uuid.UUID, str]], model: str) -> None:
        """Writes the points that are missing or out of date: one read of the index, then one batched embedding call and
        one write for all of them. Nothing is called when every point is current, which is most searches."""
        wanted = {tool_id: (text, hashlib.sha256(text.encode()).hexdigest()) for tool_id, text in texts if text}
        held = vector_store.get_tool_points(list(wanted))
        stale = [(tid, text, digest) for tid, (text, digest) in wanted.items() if held.get(tid) != (digest, model)]
        if not stale:
            return
        embeddings = await search_service.embed_texts(model, [text for _tid, text, _digest in stale])
        vector_store.upsert_tools(
            [(tid, text, digest, embedding) for (tid, text, digest), embedding in zip(stale, embeddings, strict=True)],
            model,
        )

    async def index(self, tools: Iterable[tuple[uuid.UUID, str, str, dict]]) -> None:
        """Embeds the tools of a server when they are imported or change - (id, name, description, schema) for each -
        so that the index is current before the first search. Best effort: an embedding model or an index that is down
        costs only this, the next search writes the points. Calls the model only for a text that changed."""
        try:
            model = await default_embedding_model(self.db)
            if model is not None and search_service._openai_client is not None:
                await self._ensure_points(
                    [
                        (tool_id, indexed_text(name, description, schema))
                        for tool_id, name, description, schema in tools
                    ],
                    model,
                )
        except Exception:
            logger.warning("Could not index the tools of a server, a search will", exc_info=True)
