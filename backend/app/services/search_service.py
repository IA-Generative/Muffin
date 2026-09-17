import uuid
from collections import defaultdict
from collections.abc import Sequence

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LlmSettings
from app.models.chunk import Chunk
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.collection_repository import CollectionRepository
from app.services import vector_store

# Module attribute (not closed over), same reasoning as app/routers/internal_llm.py: tests
# swap this out with monkeypatch.setattr without a live LLM hub.
_llm_settings = LlmSettings()
_openai_client = (
    AsyncOpenAI(api_key=_llm_settings.OPENAI_API_KEY, base_url=_llm_settings.OPENAI_API_BASE_URL)
    if _llm_settings.is_configured
    else None
)


class SearchService:
    """Vector search across the selected collections (§14 of the research-agent brief) - Qdrant
    holds the vectors, Postgres holds the text. A collection's chunks were embedded with that
    collection's own embedding_model (worker/document_process, at chunk creation time), so the
    query is embedded once per distinct model among the selected collections, not once overall."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.chunks = ChunkRepository(db)
        self.collections = CollectionRepository(db)

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
            query_embedding = await self._embed(model, query)
            for collection_id in collections_for_model:
                for chunk_id, score in vector_store.search(collection_id, query_embedding, limit):
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

    async def _embed(self, model: str, text: str) -> list[float]:
        result = await _openai_client.embeddings.create(model=model, input=text)
        return result.data[0].embedding
