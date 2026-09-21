import uuid
from collections import defaultdict
from collections.abc import Sequence

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.qa import QaPair
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.services import vector_store
from app.services.embedding_model_lookup import default_embedding_model

# Module attribute (not closed over), same reasoning as app/routers/internal_llm.py: tests
# swap this out with monkeypatch.setattr without a live LLM hub.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)


class SearchService:
    """Hybrid (lexical + vector) search across the selected collections (§14 of the
    research-agent brief) - Meilisearch holds the vectors and a lexical copy of the text,
    Postgres remains the source of truth for both. A collection's chunks were embedded with
    that collection's own embedding_model (worker/document_process, at chunk creation time), so
    the query is embedded once per distinct model among the selected collections, not once
    overall."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chunks = ChunkRepository(db)
        self.collections = CollectionRepository(db)
        self.qa_pairs = QaPairRepository(db)
        self.documents = DocumentRepository(db)

    async def search(
        self, collection_ids: list[uuid.UUID], query: str, limit: int
    ) -> Sequence[tuple[Chunk, str, uuid.UUID, float]]:
        if _openai_client is None:
            return []

        models_by_collection = await self.collections.get_embedding_models(collection_ids)
        collections_by_model: dict[str, list[uuid.UUID]] = defaultdict(list)
        for collection_id, model in models_by_collection.items():
            collections_by_model[model].append(collection_id)

        scored_ids: dict[uuid.UUID, float] = {}
        for model, collections_for_model in collections_by_model.items():
            try:
                query_embedding = await self._embed(model, query)
            except Exception:
                # A misconfigured/unavailable embedding model for this one group of collections
                # must not fail collections using a different, working model (§29: one bad
                # branch doesn't take the whole search down) - they just contribute no results.
                logger.exception(f"Failed to embed the search query with model '{model}'")
                continue
            for collection_id in collections_for_model:
                for chunk_id, score in vector_store.search(collection_id, query, query_embedding, limit):
                    scored_ids[chunk_id] = max(score, scored_ids.get(chunk_id, float("-inf")))

        top_ids = sorted(scored_ids, key=lambda chunk_id: scored_ids[chunk_id], reverse=True)[:limit]
        rows = await self.chunks.get_by_ids(top_ids)
        # `IN (...)` doesn't preserve order - re-sort by score since that's the ranking callers
        # (the research agent's search_knowledge_base) actually rely on.
        return sorted(
            (
                (chunk, document_name, collection_id, scored_ids[chunk.id])
                for chunk, document_name, collection_id in rows
            ),
            key=lambda row: row[3],
            reverse=True,
        )

    async def search_qa(
        self, collection_ids: list[uuid.UUID], query: str, limit: int
    ) -> Sequence[tuple[QaPair, uuid.UUID, float]]:
        """QA-first retrieval tier (§ research agent): a previously answered question, matched by
        embedding its *question* text the same way a chunk's body text is - same vector space,
        same collection, just filtered to QA-kind points (see vector_store.search_qa)."""
        if _openai_client is None:
            return []

        models_by_collection = await self.collections.get_embedding_models(collection_ids)
        collections_by_model: dict[str, list[uuid.UUID]] = defaultdict(list)
        for collection_id, model in models_by_collection.items():
            collections_by_model[model].append(collection_id)

        scored_by_id: dict[uuid.UUID, tuple[uuid.UUID, float]] = {}
        for model, collections_for_model in collections_by_model.items():
            try:
                query_embedding = await self._embed(model, query)
            except Exception:
                logger.exception(f"Failed to embed the QA search query with model '{model}'")
                continue
            for collection_id in collections_for_model:
                for qa_pair_id, score in vector_store.search_qa(collection_id, query, query_embedding, limit):
                    if qa_pair_id not in scored_by_id or score > scored_by_id[qa_pair_id][1]:
                        scored_by_id[qa_pair_id] = (collection_id, score)

        top_ids = sorted(scored_by_id, key=lambda qa_pair_id: scored_by_id[qa_pair_id][1], reverse=True)[:limit]
        rows = await self.qa_pairs.get_by_ids(top_ids)
        return sorted(
            ((qa_pair, scored_by_id[qa_pair.id][0], scored_by_id[qa_pair.id][1]) for qa_pair in rows),
            key=lambda row: row[2],
            reverse=True,
        )

    async def search_summaries(
        self, collection_ids: list[uuid.UUID], query: str, limit: int
    ) -> Sequence[tuple[Document, float]]:
        """Tier 2 of the research agent's retrieval cascade (§ QA -> summaries -> chunks): the
        top-K documents whose *summary* embedding is closest to the query - never every summary
        in the collection, which wouldn't scale to a collection with hundreds of documents."""
        if _openai_client is None:
            return []

        models_by_collection = await self.collections.get_embedding_models(collection_ids)
        collections_by_model: dict[str, list[uuid.UUID]] = defaultdict(list)
        for collection_id, model in models_by_collection.items():
            collections_by_model[model].append(collection_id)

        scored_ids: dict[uuid.UUID, float] = {}
        for model, collections_for_model in collections_by_model.items():
            try:
                query_embedding = await self._embed(model, query)
            except Exception:
                logger.exception(f"Failed to embed the summary search query with model '{model}'")
                continue
            for collection_id in collections_for_model:
                for document_id, score in vector_store.search_summaries(collection_id, query, query_embedding, limit):
                    scored_ids[document_id] = max(score, scored_ids.get(document_id, float("-inf")))

        top_ids = sorted(scored_ids, key=lambda document_id: scored_ids[document_id], reverse=True)[:limit]
        rows = await self.documents.get_by_ids(top_ids)
        return sorted(((document, scored_ids[document.id]) for document in rows), key=lambda row: row[1], reverse=True)

    async def search_collections(
        self, collection_ids: list[uuid.UUID], query: str, limit: int
    ) -> Sequence[tuple[uuid.UUID, float]]:
        """Vector search over collection *descriptions*, not their content (§ VDB routing
        pre-filter, §122 file-filing suggestion). Unlike search/search_qa/search_summaries
        above, every collection's description shares one embedding space (the admin-configured
        default_embedding_model - see app/services/embedding_model_lookup.py and
        worker/document_process's update_collection_description), so the query is only ever
        embedded once here, never once per collection's own chunk embedding_model."""
        if _openai_client is None or not collection_ids:
            return []
        model = await default_embedding_model(self.db)
        if model is None:
            return []
        try:
            query_embedding = await self._embed(model, query)
        except Exception:
            logger.exception("Failed to embed the collection-search query")
            return []
        return vector_store.search_collections(query, query_embedding, collection_ids, limit)

    async def _embed(self, model: str, text: str) -> list[float]:
        return await embed_text(model, text)


async def embed_text(model: str, text: str) -> list[float]:
    """Shared by every embedding call site that isn't a chunk (whose embedding is always computed
    worker-side and sent along, see ChunkCreate.embedding): query embeddings for chunk/QA/summary
    search all go through this exact same client/call."""
    result = await _openai_client.embeddings.create(model=model, input=text)
    return result.data[0].embedding
