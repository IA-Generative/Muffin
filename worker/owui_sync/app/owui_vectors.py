"""The chunks Open WebUI keeps in its Qdrant (#453), read where they are: Muffin copies none of the vectors.

Open WebUI (classic mode, `ENABLE_QDRANT_MULTITENANCY_MODE=false`) has one collection per knowledge base,
`<prefix>_<knowledge base id>`, with one point per chunk: an unnamed dense vector and the payload
`{"text": ..., "metadata": {"file_id": ..., "start_index": ..., ...}}` (docs/owui-test-instance.md).
"""

from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.config import settings

_PAGE = 256


@dataclass(frozen=True)
class OwuiChunk:
    id: str
    text: str


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
