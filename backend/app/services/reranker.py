"""The reranking of passages (#511): a model reads the question with each passage and rates the passage.

It changes which passages a search keeps and in what order, never the score the search exposes (the cosine, which the
agent's thresholds are set on): the rating is a separate number. It is also only ever a refinement - the service
being slow, down or answering something unexpected leaves the search with the order it had, and a warning in the log."""

import httpx
from loguru import logger

from app.config import RerankSettings

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = RerankSettings()


def is_enabled() -> bool:
    return _settings.enabled


def candidates() -> int:
    return _settings.RERANK_CANDIDATES


async def rerank(query: str, passages: list[str]) -> list[float] | None:
    """The rating of each passage for the question, in the order given - None when there is nothing to reorder (fewer
    than two passages, or no service configured) or the service could not be used, so the caller keeps its order."""
    if not _settings.enabled or len(passages) < 2:
        return None
    headers = {"Content-Type": "application/json"}
    if key := _settings.RERANK_API_KEY.get_secret_value():
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "query": query,
        "documents": [passage[: _settings.RERANK_PASSAGE_MAX_CHARS] for passage in passages],
        "top_n": len(passages),
    }
    if _settings.RERANK_MODEL:
        body["model"] = _settings.RERANK_MODEL
    try:
        async with httpx.AsyncClient(timeout=_settings.RERANK_TIMEOUT_SECONDS) as client:
            response = await client.post(_settings.RERANK_API_URL, json=body, headers=headers)
            response.raise_for_status()
        scores: list[float | None] = [None] * len(passages)
        for result in response.json()["results"]:
            scores[int(result["index"])] = float(result["relevance_score"])
        if any(score is None for score in scores):
            raise ValueError("the service did not rate every passage")
        return scores  # type: ignore[return-value]
    except Exception as error:
        # The type of the error, not the response: it could hold the passages of a document.
        logger.warning(f"The reranking service could not be used, the search keeps its order: {type(error).__name__}")
        return None
