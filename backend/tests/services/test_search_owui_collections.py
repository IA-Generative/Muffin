"""A collection copied from Open WebUI (#453) is searched with the others: the same question, the same score, and
its chunks come back from Postgres, where the synchronisation put them under the ids of their points."""

import uuid

import pytest
from sqlalchemy import delete

from app.db import async_session_factory
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentType
from app.services import search_service, vector_store
from app.services.search_service import SearchService


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _collection(session, name: str, *, external_id: str | None = None) -> tuple[Collection, Chunk]:
    collection = Collection(
        owner_id="u", name=name, source="owui" if external_id else "muffin", external_id=external_id
    )
    collection.settings = CollectionSettings(embedding_model="bge")
    session.add(collection)
    await session.flush()
    document = Document(collection_id=collection.id, name=f"{name}.pdf", type=DocumentType.FILE)
    session.add(document)
    await session.flush()
    chunk = Chunk(id=uuid.uuid4(), document_id=document.id, index=0, text=f"text of {name}", token_count=3)
    session.add(chunk)
    await session.flush()
    return collection, chunk


@pytest.fixture
def embedding(monkeypatch):
    async def embed(self, model, text):
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(search_service, "_openai_client", object())
    monkeypatch.setattr(SearchService, "_embed", embed)


async def test_the_chunks_of_a_copied_collection_come_back_with_the_others(embedding, monkeypatch):
    async with async_session_factory() as session:
        copied, copied_chunk = await _collection(session, "copied", external_id="kb1")
        own, own_chunk = await _collection(session, "own")
        await session.commit()
        asked = {}

        def external(name, query_embedding, limit):
            asked["name"] = name
            return [(copied_chunk.id, 0.8)]

        monkeypatch.setattr(vector_store, "search_external", external)
        monkeypatch.setattr(
            vector_store, "search", lambda cid, q, e, limit: [(own_chunk.id, 0.9)] if cid == own.id else []
        )

        rows = await SearchService(session).search([copied.id, own.id], "question", 5)

    assert asked["name"] == vector_store.external_collection_name("kb1")
    assert [(chunk.id, collection_id, score) for chunk, _, collection_id, score in rows] == [
        (own_chunk.id, own.id, 0.9),
        (copied_chunk.id, copied.id, 0.8),
    ]


async def test_a_copied_collection_is_never_searched_in_an_index_of_muffins(embedding, monkeypatch):
    async with async_session_factory() as session:
        copied, copied_chunk = await _collection(session, "copied", external_id="kb1")
        await session.commit()
        monkeypatch.setattr(vector_store, "search_external", lambda name, e, limit: [(copied_chunk.id, 0.7)])
        monkeypatch.setattr(vector_store, "search", lambda *args: pytest.fail("looked for an index of Muffin's"))

        rows = await SearchService(session).search([copied.id], "question", 5)

    assert [chunk.id for chunk, *_ in rows] == [copied_chunk.id]


async def test_a_copied_collection_that_cannot_be_searched_does_not_take_the_others_down(embedding, monkeypatch):
    async with async_session_factory() as session:
        copied, _ = await _collection(session, "copied", external_id="kb1")
        own, own_chunk = await _collection(session, "own")
        await session.commit()

        monkeypatch.setattr(vector_store, "_exists", lambda name: True)
        monkeypatch.setattr(
            vector_store._client, "query_points", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("dim"))
        )
        monkeypatch.setattr(
            vector_store, "search", lambda cid, q, e, limit: [(own_chunk.id, 0.9)] if cid == own.id else []
        )

        rows = await SearchService(session).search([copied.id, own.id], "question", 5)

    assert [chunk.id for chunk, *_ in rows] == [own_chunk.id]


async def test_every_kind_of_point_of_a_collection_of_muffin_is_searched_with_no_cascade(embedding, monkeypatch):
    async with async_session_factory() as session:
        own, _ = await _collection(session, "own")
        await session.commit()
        asked = {}

        def search_any(collection_id, query, query_embedding, limit):
            asked["collection"] = collection_id
            return [(uuid.uuid4(), 0.5)]

        monkeypatch.setattr(vector_store, "search_any", search_any)
        monkeypatch.setattr(vector_store, "search", lambda *args: pytest.fail("only the chunks were looked at"))

        hits = await SearchService(session).search_points([own.id], "question", 5)

    assert asked["collection"] == own.id and [(collection_id, score) for _, collection_id, score in hits] == [
        (own.id, 0.5)
    ]


async def test_a_copied_collection_is_searched_in_the_other_systems_qdrant_by_search_points(embedding, monkeypatch):
    async with async_session_factory() as session:
        copied, copied_chunk = await _collection(session, "copied", external_id="kb1")
        await session.commit()
        monkeypatch.setattr(vector_store, "search_external", lambda name, e, limit: [(copied_chunk.id, 0.7)])
        monkeypatch.setattr(vector_store, "search_any", lambda *args: pytest.fail("looked for an index of Muffin's"))

        hits = await SearchService(session).search_points([copied.id], "question", 5)

    assert hits == [(copied_chunk.id, copied.id, 0.7)]


async def test_search_points_orders_every_collection_together_and_keeps_the_best(embedding, monkeypatch):
    async with async_session_factory() as session:
        one, _ = await _collection(session, "one")
        two, _ = await _collection(session, "two")
        await session.commit()
        points = {one.id: [(uuid.uuid4(), 0.4), (uuid.uuid4(), 0.9)], two.id: [(uuid.uuid4(), 0.6)]}
        monkeypatch.setattr(vector_store, "search_any", lambda cid, q, e, limit: points[cid])

        hits = await SearchService(session).search_points([one.id, two.id], "question", 2)

    assert [score for _, _, score in hits] == [0.9, 0.6]


async def test_a_copy_muffin_took_over_is_searched_in_its_own_index_not_the_other_systems(embedding, monkeypatch):
    from datetime import UTC, datetime

    async with async_session_factory() as session:
        adopted, _ = await _collection(session, "adopted", external_id="kb1")
        adopted.adopted_at = datetime.now(UTC)
        await session.commit()
        monkeypatch.setattr(
            vector_store, "search_external", lambda *args: pytest.fail("read the other system's Qdrant")
        )
        searched = {}

        def search_any(collection_id, query, query_embedding, limit):
            searched["collection"] = collection_id
            return [(uuid.uuid4(), 0.5)]

        monkeypatch.setattr(vector_store, "search_any", search_any)
        monkeypatch.setattr(vector_store, "search", lambda cid, q, e, limit: [])

        await SearchService(session).search_points([adopted.id], "question", 5)
        await SearchService(session).search([adopted.id], "question", 5)

    assert searched["collection"] == adopted.id
