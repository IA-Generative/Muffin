"""The reranking of a search (#511): the service's ratings change which passages are kept and their order, never the
cosine a search exposes - and a service that cannot be used changes nothing."""

import json
import uuid

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentType
from app.services import reranker, search_service, vector_store
from app.services.search_service import SearchService


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


@pytest.fixture
def service_on(monkeypatch):
    monkeypatch.setattr(reranker._settings, "RERANK_API_URL", "http://rerank.test/v1/rerank")
    monkeypatch.setattr(reranker._settings, "RERANK_API_KEY", SecretStr("secret"))
    monkeypatch.setattr(reranker._settings, "RERANK_MODEL", "bge-reranker")
    monkeypatch.setattr(reranker._settings, "RERANK_CANDIDATES", 10)


@pytest.fixture
def embedding(monkeypatch):
    async def embed(self, model, text):
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(search_service, "_openai_client", object())
    monkeypatch.setattr(SearchService, "_embed", embed)


def _http(monkeypatch, handler):
    """The reranking service, answered by `handler` instead of a network."""
    real = httpx.AsyncClient
    monkeypatch.setattr(
        reranker.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)
    )


def _rates(ratings: dict[str, float]):
    """A service that rates a passage by its text."""

    def handler(request: httpx.Request) -> httpx.Response:
        documents = json.loads(request.content)["documents"]
        results = [{"index": i, "relevance_score": ratings[text]} for i, text in enumerate(documents)]
        return httpx.Response(200, json={"results": results})

    return handler


async def _collection(session, name: str, texts: list[str], *, rerank: bool) -> tuple[Collection, list[Chunk]]:
    collection = Collection(owner_id="u", name=name)
    collection.settings = CollectionSettings(embedding_model="bge", rerank_enabled=rerank)
    session.add(collection)
    await session.flush()
    document = Document(collection_id=collection.id, name=f"{name}.pdf", type=DocumentType.FILE)
    session.add(document)
    await session.flush()
    chunks = [
        Chunk(id=uuid.uuid4(), document_id=document.id, index=i, text=text, token_count=3)
        for i, text in enumerate(texts)
    ]
    session.add_all(chunks)
    await session.flush()
    return collection, chunks


def _cosines(monkeypatch, scores: dict[uuid.UUID, float]):
    """Qdrant, answering the chunks it knows, best cosine first, at most `limit` of them."""

    def search(collection_id, query, embedding, limit):
        found = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return found[:limit]

    monkeypatch.setattr(vector_store, "search", search)


# --- the client ---


async def test_the_client_sends_the_question_and_the_passages_in_the_format_of_cohere_jina_and_vllm(
    service_on, monkeypatch
):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]}
        )

    _http(monkeypatch, handler)

    ratings = await reranker.rerank("telework?", ["first", "second"])

    assert ratings == [0.1, 0.9]  # by passage, not in the order the service listed them
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {
        "query": "telework?",
        "documents": ["first", "second"],
        "top_n": 2,
        "model": "bge-reranker",
    }


async def test_a_passage_is_cut_before_it_is_sent(service_on, monkeypatch):
    monkeypatch.setattr(reranker._settings, "RERANK_PASSAGE_MAX_CHARS", 5)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["documents"] = json.loads(request.content)["documents"]
        return httpx.Response(
            200, json={"results": [{"index": 0, "relevance_score": 1}, {"index": 1, "relevance_score": 0}]}
        )

    _http(monkeypatch, handler)

    await reranker.rerank("q", ["abcdefghij", "kl"])

    assert seen["documents"] == ["abcde", "kl"]


async def test_nothing_is_asked_without_a_service_or_with_fewer_than_two_passages(service_on, monkeypatch):
    calls = []
    _http(monkeypatch, lambda request: calls.append(request) or httpx.Response(500))

    assert await reranker.rerank("q", []) is None
    assert await reranker.rerank("q", ["only one"]) is None
    monkeypatch.setattr(reranker._settings, "RERANK_API_URL", "")
    assert await reranker.rerank("q", ["a", "b"]) is None
    assert calls == []


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(500),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]}),  # one passage not rated
        httpx.Response(200, content=b"not json"),
    ],
)
async def test_a_service_that_fails_gives_nothing_and_is_logged(service_on, monkeypatch, answer):
    from loguru import logger

    _http(monkeypatch, lambda request: answer)
    logged = []
    handle = logger.add(lambda message: logged.append(str(message)), level="WARNING")
    try:
        assert await reranker.rerank("q", ["a", "b"]) is None
    finally:
        logger.remove(handle)

    assert any("keeps its order" in line for line in logged)


async def test_a_service_that_is_too_slow_gives_nothing(service_on, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    _http(monkeypatch, handler)

    assert await reranker.rerank("q", ["a", "b"]) is None


# --- a search ---


async def test_the_ratings_choose_and_order_the_passages_but_the_score_stays_the_cosine(
    service_on, embedding, monkeypatch
):
    async with async_session_factory() as session:
        collection, chunks = await _collection(session, "c", ["close", "far", "middle"], rerank=True)
        await session.commit()
        _cosines(monkeypatch, {chunks[0].id: 0.9, chunks[1].id: 0.5, chunks[2].id: 0.7})
        _http(monkeypatch, _rates({"close": 0.1, "far": 0.99, "middle": 0.5}))
        service = SearchService(session)

        rows = await service.search([collection.id], "question", 2)

    # "far" is the best answer though the farthest in cosine; "close" is dropped though the closest.
    assert [(chunk.text, score) for chunk, _, _, score in rows] == [("far", 0.5), ("middle", 0.7)]
    assert service.rerank_scores == {chunks[1].id: 0.99, chunks[2].id: 0.5, chunks[0].id: 0.1}


async def test_more_candidates_than_the_limit_are_read_when_reranking(service_on, embedding, monkeypatch):
    asked = []
    async with async_session_factory() as session:
        collection, chunks = await _collection(session, "c", ["a", "b", "c"], rerank=True)
        await session.commit()

        def search(collection_id, query, embedding, limit):
            asked.append(limit)
            return [(chunk.id, 0.5) for chunk in chunks][:limit]

        monkeypatch.setattr(vector_store, "search", search)
        _http(monkeypatch, _rates({"a": 1, "b": 2, "c": 3}))

        rows = await SearchService(session).search([collection.id], "question", 1)

    assert asked == [10] and [chunk.text for chunk, *_ in rows] == ["c"]


async def test_without_a_service_nothing_changes_and_no_call_is_made(embedding, monkeypatch):
    calls = []
    asked = []
    async with async_session_factory() as session:
        collection, chunks = await _collection(session, "c", ["a", "b"], rerank=True)
        await session.commit()

        def search(collection_id, query, embedding, limit):
            asked.append(limit)
            return [(chunks[0].id, 0.9), (chunks[1].id, 0.8)]

        monkeypatch.setattr(vector_store, "search", search)
        _http(monkeypatch, lambda request: calls.append(request) or httpx.Response(500))
        service = SearchService(session)

        rows = await service.search([collection.id], "question", 5)

    assert [chunk.text for chunk, *_ in rows] == ["a", "b"]
    assert calls == [] and asked == [5] and service.rerank_scores == {}


async def test_a_collection_that_did_not_ask_for_it_is_not_reranked(service_on, embedding, monkeypatch):
    calls = []
    async with async_session_factory() as session:
        collection, chunks = await _collection(session, "c", ["a", "b"], rerank=False)
        await session.commit()
        _cosines(monkeypatch, {chunks[0].id: 0.9, chunks[1].id: 0.8})
        _http(monkeypatch, lambda request: calls.append(request) or httpx.Response(500))

        rows = await SearchService(session).search([collection.id], "question", 5)

    assert [chunk.text for chunk, *_ in rows] == ["a", "b"] and calls == []


async def test_one_collection_that_asked_for_it_reranks_the_search_of_several(service_on, embedding, monkeypatch):
    async with async_session_factory() as session:
        asking, asking_chunks = await _collection(session, "asking", ["a1"], rerank=True)
        quiet, quiet_chunks = await _collection(session, "quiet", ["q1"], rerank=False)
        await session.commit()
        monkeypatch.setattr(
            vector_store,
            "search",
            lambda cid, q, e, limit: [(asking_chunks[0].id, 0.9)] if cid == asking.id else [(quiet_chunks[0].id, 0.6)],
        )
        _http(monkeypatch, _rates({"a1": 0.2, "q1": 0.8}))

        rows = await SearchService(session).search([asking.id, quiet.id], "question", 5)

    assert [chunk.text for chunk, *_ in rows] == ["q1", "a1"]


@pytest.mark.parametrize("answer", [httpx.Response(500), httpx.Response(200, json={})])
async def test_a_search_whose_service_is_down_answers_as_before(service_on, embedding, monkeypatch, answer):
    async with async_session_factory() as session:
        collection, chunks = await _collection(session, "c", ["a", "b", "c"], rerank=True)
        await session.commit()
        _cosines(monkeypatch, {chunks[0].id: 0.9, chunks[1].id: 0.8, chunks[2].id: 0.7})
        _http(monkeypatch, lambda request: answer)
        service = SearchService(session)

        rows = await service.search([collection.id], "question", 2)

    assert [(chunk.text, score) for chunk, _, _, score in rows] == [("a", 0.9), ("b", 0.8)]
    assert service.rerank_scores == {}
