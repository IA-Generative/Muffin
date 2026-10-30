import json
import uuid
from collections.abc import Sequence

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import KeycloakSettings, LlmSettings, McpSettings
from app.core.security.factory import RequestContext
from app.models.token_usage import TokenUsageKind
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.collection_hierarchy_repository import CollectionHierarchyRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.schemas.internal_pipeline import LlmUsageContext
from app.schemas.mcp import SearchResult, SearchSource, SubQueryResult, SuggestedCollection, SuggestedCollections
from app.services import chat_model_lookup
from app.services.page_highlights import chunk_pages_of
from app.services.search_service import SearchService
from app.services.usage_service import UsageService

# Same module-level-client pattern as the other services that call the hub: tests swap it out.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)
_mcp_settings = McpSettings()
_keycloak_settings = KeycloakSettings()

_SPLIT_PROMPT = (
    "Split the user's question into independent sub-questions, each of which can be looked up on its own, in the "
    "language of the question. A question that asks one thing stays as it is. Give at most {maximum}. Respond only "
    "with a JSON array of strings."
)
_MAX_SUB_QUERY_CHARS = 500


class NoAccessibleCollectionError(ValueError):
    """The collections asked for are not all ones the caller may read."""


def collection_url(collection_id: uuid.UUID) -> str:
    """Where Muffin's interface opens a collection: the link a client shows, whichever client asked."""
    return f"{_keycloak_settings.FRONTEND_URL.rstrip('/')}/collections/{collection_id}"


def document_url(collection_id: uuid.UUID, document_id: uuid.UUID | None) -> str:
    return (
        collection_url(collection_id)
        if document_id is None
        else f"{collection_url(collection_id)}/documents/{document_id}"
    )


def _bounded(value: int | None, default: int, ceiling: int) -> int:
    return max(1, min(value if value is not None else default, ceiling))


class McpSearchService:
    """What the MCP tools do (#467): propose the collections a question is about, and search them - question split
    into sub-questions, each sent to its best collections - returning the sources found and writing no answer. Always
    within the collections the caller can read."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.collections = CollectionRepository(db)
        self.hierarchy = CollectionHierarchyRepository(db)
        self.search_service = SearchService(db)

    # -- tool 1 -----------------------------------------------------------------------------------

    async def suggest_collections(self, user: RequestContext, query: str, limit: int | None) -> SuggestedCollections:
        accessible = await self.collections.accessible_ids(user.user_id, user.groups)
        limit = _bounded(limit, _mcp_settings.MCP_SUGGEST_LIMIT, _mcp_settings.MCP_SUGGEST_LIMIT_CEILING)
        return SuggestedCollections(query=query, collections=await self._suggest(accessible, query, limit))

    async def _suggest(self, accessible: set[uuid.UUID], query: str, limit: int) -> list[SuggestedCollection]:
        """The collections whose description is closest to the question, no model involved but the embedding."""
        scored = await self.search_service.search_collections(list(accessible), query, limit)
        if not scored:
            return []
        scores = dict(scored)
        rows = {collection.id: collection for collection in await self.collections.get_by_ids(list(scores))}
        names = await self.hierarchy.names(list(scores))
        chains = await self.hierarchy.ancestor_chains(list(scores))
        suggestions = []
        for collection_id, score in scored:
            collection = rows.get(collection_id)
            if collection is None:
                continue
            # Only the ancestors the caller may read: the name of one they may not is not theirs to know (#216).
            path = [ancestor.name for ancestor in reversed(chains.get(collection_id, [])) if ancestor.id in accessible]
            suggestions.append(
                SuggestedCollection(
                    id=collection_id,
                    name=names[collection_id].name,
                    path=[*path, names[collection_id].name],
                    description=collection.description or "",
                    score=score,
                    url=collection_url(collection_id),
                )
            )
        return suggestions

    # -- tool 2 -----------------------------------------------------------------------------------

    async def search(
        self,
        user: RequestContext,
        query: str,
        collection_ids: Sequence[uuid.UUID] | None,
        model: str | None,
        max_sub_queries: int | None,
        max_collections: int | None,
        limit: int | None,
    ) -> SearchResult:
        accessible = await self.collections.accessible_ids(user.user_id, user.groups)
        scope: list[uuid.UUID] | None = None
        if collection_ids:
            scope = list(dict.fromkeys(collection_ids))
            if any(collection_id not in accessible for collection_id in scope):
                raise NoAccessibleCollectionError("Some of the collections asked for do not exist or cannot be read")
        max_sub_queries = _bounded(
            max_sub_queries, _mcp_settings.MCP_SEARCH_MAX_SUB_QUERIES, _mcp_settings.MCP_SEARCH_MAX_SUB_QUERIES_CEILING
        )
        max_collections = _bounded(
            max_collections, _mcp_settings.MCP_SEARCH_MAX_COLLECTIONS, _mcp_settings.MCP_SEARCH_MAX_COLLECTIONS_CEILING
        )
        limit = _bounded(limit, _mcp_settings.MCP_SEARCH_LIMIT, _mcp_settings.MCP_SEARCH_LIMIT_CEILING)

        used_model, sub_queries = await self._split(user, query, model, max_sub_queries)
        results = []
        for sub_query in sub_queries:
            if scope is not None:
                suggested = await self._described(scope, accessible)
            else:
                suggested = await self._suggest(accessible, sub_query, max_collections)
            hits = await self.search_service.search_points([item.id for item in suggested], sub_query, limit)
            results.append(
                SubQueryResult(text=sub_query, collections=suggested, sources=await self._sources(hits, suggested))
            )
        return SearchResult(query=query, model=used_model, sub_queries=results)

    async def _described(
        self, collection_ids: list[uuid.UUID], accessible: set[uuid.UUID]
    ) -> list[SuggestedCollection]:
        """The collections the caller named, as they are listed - with no score, since none was asked of them."""
        rows = {collection.id: collection for collection in await self.collections.get_by_ids(collection_ids)}
        chains = await self.hierarchy.ancestor_chains(collection_ids)
        described = []
        for collection_id in collection_ids:
            collection = rows.get(collection_id)
            if collection is None:
                continue
            path = [ancestor.name for ancestor in reversed(chains.get(collection_id, [])) if ancestor.id in accessible]
            described.append(
                SuggestedCollection(
                    id=collection_id,
                    name=collection.name,
                    path=[*path, collection.name],
                    description=collection.description or "",
                    score=0.0,
                    url=collection_url(collection_id),
                )
            )
        return described

    async def _split(
        self, user: RequestContext, query: str, model: str | None, maximum: int
    ) -> tuple[str | None, list[str]]:
        """The question's sub-questions, from one simple call to a chat model. A call that fails, or answers
        something else than a list, leaves the question whole: it is then its own and only sub-question."""
        if maximum <= 1 or _openai_client is None:
            return None, [query]
        try:
            model = model or _mcp_settings.MCP_SEARCH_MODEL or await chat_model_lookup.default_chat_model()
            if not model:
                return None, [query]
            completion = await _openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SPLIT_PROMPT.format(maximum=maximum)},
                    {"role": "user", "content": query},
                ],
            )
            usage = completion.usage
            await UsageService(self.db).record(
                LlmUsageContext(step="mcp_split", user_id=user.user_id),
                TokenUsageKind.CHAT,
                model,
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
            )
            parsed = json.loads(_strip_fence(completion.choices[0].message.content or ""))
            if not isinstance(parsed, list):
                raise ValueError("not a list")
            texts = [text.strip()[:_MAX_SUB_QUERY_CHARS] for text in parsed if isinstance(text, str) and text.strip()]
            return model, list(dict.fromkeys(texts))[:maximum] or [query]
        except Exception:
            logger.exception("Failed to split the question, it is searched whole")
            return None, [query]

    async def _sources(
        self, hits: list[tuple[uuid.UUID, uuid.UUID, float]], collections: list[SuggestedCollection]
    ) -> list[SearchSource]:
        """The points a search returned, put back into what they are: a chunk, a QA pair or a document's summary,
        found by id in Postgres (the Qdrant payload is only for searching). A point Postgres no longer knows - a
        stale vector - is dropped."""
        if not hits:
            return []
        ids = [point_id for point_id, _, _ in hits]
        names = {item.id: item.name for item in collections}
        chunks = {chunk.id: (chunk, name) for chunk, name, _ in await ChunkRepository(self.db).get_by_ids(ids)}
        pairs = {pair.id: pair for pair in await QaPairRepository(self.db).get_by_ids(ids)}
        documents = {document.id: document for document in await DocumentRepository(self.db).get_by_ids(ids)}
        # A summary is the document's own id; a document itself is only a hit as that.
        sources = []
        for point_id, collection_id, score in hits:
            common = {"score": score, "collection_id": collection_id, "collection_name": names.get(collection_id, "")}
            if point_id in chunks:
                chunk, document_name = chunks[point_id]
                pages = chunk_pages_of(chunk.extras or {})
                sources.append(
                    SearchSource(
                        kind="chunk",
                        text=chunk.text,
                        document_id=chunk.document_id,
                        document_name=document_name,
                        page=pages[0] if pages else None,
                        url=document_url(collection_id, chunk.document_id),
                        **common,
                    )
                )
            elif point_id in pairs:
                pair = pairs[point_id]
                sources.append(
                    SearchSource(
                        kind="qa",
                        text=f"{pair.question}\n{pair.answer}",
                        document_id=pair.document_id,
                        document_name=pair.document.name if pair.document else None,
                        page=pair.source_page,
                        url=document_url(collection_id, pair.document_id),
                        **common,
                    )
                )
            elif point_id in documents and documents[point_id].summary:
                document = documents[point_id]
                sources.append(
                    SearchSource(
                        kind="summary",
                        text=document.summary,
                        document_id=document.id,
                        document_name=document.name,
                        page=None,
                        url=document_url(collection_id, document.id),
                        **common,
                    )
                )
        return sources


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped
