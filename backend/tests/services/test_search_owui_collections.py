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
