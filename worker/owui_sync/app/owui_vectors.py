"""The chunks Open WebUI keeps in its Qdrant (#453), read where they are: Muffin copies none of the vectors.

Open WebUI (classic mode, `ENABLE_QDRANT_MULTITENANCY_MODE=false`) has one collection per knowledge base,
`<prefix>_<knowledge base id>`, with one point per chunk: an unnamed dense vector and the payload
`{"text": ..., "metadata": {"file_id": ..., "start_index": ..., ...}}` (docs/owui-test-instance.md).
"""

import ast
from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient, models

from app.config import settings

_PAGE = 256
# How many chunks are read to learn which models made the vectors: a knowledge base is embedded by one model at a
# time, so a sample shows a model that changed - it is not a count.
_SAMPLE = 100


@dataclass(frozen=True)
class OwuiChunk:
    id: str
    text: str


@dataclass(frozen=True)
class CollectionInfo:
    """What a knowledge base's collection in Qdrant says about the vectors it holds."""

    exists: bool
    # Size of its one unnamed vector, None when the collection is not in Qdrant or does not have that shape.
    dimension: int | None
    # The embedding models its chunks say they were made with (`metadata.embedding_config`).
    models: frozenset[str]


def _model_of(embedding_config: Any) -> str | None:
    """Open WebUI writes `{'engine': 'openai', 'model': 'bge'}` into each chunk - as a string of a Python dict."""
    if isinstance(embedding_config, str):
        try:
            embedding_config = ast.literal_eval(embedding_config)
        except (ValueError, SyntaxError):
            return None
    model = embedding_config.get("model") if isinstance(embedding_config, dict) else None
    return str(model) if model else None


class OwuiVectors:
    def __init__(self, client: QdrantClient | None = None, prefix: str | None = None) -> None:
        self._client = client or QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None)
        self._prefix = settings.OWUI_QDRANT_PREFIX if prefix is None else prefix

    def collection_name(self, knowledge_id: str) -> str:
        return f"{self._prefix}_{knowledge_id}"

    def chunks(self, knowledge_id: str, file_id: str) -> list[OwuiChunk]:
        """The chunks of a file in a knowledge base, in the order of the file (their `start_index`)."""
        found: list[tuple[int, OwuiChunk]] = []
        file_filter = models.Filter(
            must=[models.FieldCondition(key="metadata.file_id", match=models.MatchValue(value=file_id))]
        )
        offset = None
        while True:
            points, offset = self._client.scroll(
                self.collection_name(knowledge_id),
                scroll_filter=file_filter,
                limit=_PAGE,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                start = (payload.get("metadata") or {}).get("start_index")
                found.append(
                    (start if isinstance(start, int) else 0, OwuiChunk(str(point.id), payload.get("text") or ""))
                )
            if offset is None:
                break
        # Stable: chunks with no usable start keep the order the store gave them.
        found.sort(key=lambda item: item[0])
        return [chunk for _, chunk in found]

    def inspect(self, knowledge_id: str) -> CollectionInfo:
        """The dimension of a knowledge base's vectors and the models its chunks were made with."""
        name = self.collection_name(knowledge_id)
        if not self._client.collection_exists(name):
            return CollectionInfo(exists=False, dimension=None, models=frozenset())
        vectors = self._client.get_collection(name).config.params.vectors
        dimension = vectors.size if isinstance(vectors, models.VectorParams) else None
        points, _ = self._client.scroll(name, limit=_SAMPLE, with_payload=True, with_vectors=False)
        found = {_model_of((point.payload or {}).get("metadata", {}).get("embedding_config")) for point in points}
        return CollectionInfo(exists=True, dimension=dimension, models=frozenset(found - {None}))
