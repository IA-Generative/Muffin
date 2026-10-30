"""A task of the pipeline run twice - a redelivery after a crash - leaves the same state as one run
(#299), and what the pipeline derives from a document goes with it."""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.security import worker_auth
from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentPage, DocumentStatus
from app.models.entity import Entity, EntityDocument, Relation
from app.models.qa import QaOrigin, QaPair
from app.repositories.entity_repository import EntityRepository
from app.services import vector_store
from app.services.document_upload_service import DocumentUploadService

API_KEY = "test-worker-key"
USER = RequestContext(user_id="dev-user", email="dev@example.com", roles=["user"], is_admin=False, groups=[])


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


@pytest.fixture
def search_index(monkeypatch):
    """Qdrant and RustFS replaced: the points and objects that are written and removed."""
    calls = {"chunks_upserted": [], "chunks_deleted": [], "qa_deleted": [], "objects_deleted": []}
    monkeypatch.setattr(
        vector_store,
        "upsert_chunk_embedding",
        lambda collection_id, chunk_id, embedding, text, model, document_id=None: calls["chunks_upserted"].append(
            chunk_id
        ),
    )
    monkeypatch.setattr(vector_store, "delete_chunk_embeddings", lambda c, ids: calls["chunks_deleted"].extend(ids))
    monkeypatch.setattr(vector_store, "delete_qa_embeddings", lambda c, ids: calls["qa_deleted"].extend(ids))
    monkeypatch.setattr(vector_store, "delete_document_embeddings", lambda *args: None)
    monkeypatch.setattr(vector_store, "upsert_qa_embedding", lambda *args: None)
    monkeypatch.setattr("app.core.storage.delete_objects", lambda keys: calls["objects_deleted"].extend(keys))
    return calls


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _collection_with_document() -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="report.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def _rows(model, document_id):
    async with async_session_factory() as session:
        result = await session.execute(select(model).where(model.document_id == document_id))
        return result.scalars().all()


# -- pages and chunks are upserts ---------------------------------------------------------------


async def test_a_page_written_twice_is_one_page(client, search_index):
    _, document_id = await _collection_with_document()
    url = f"/api/internal/documents/{document_id}/pages"

    first = await client.post(url, headers=_headers(), json={"page_number": 1, "content": "first", "screenshot": "a"})
    second = await client.post(url, headers=_headers(), json={"page_number": 1, "content": "second", "screenshot": "b"})

    assert first.status_code == second.status_code == 201
    (page,) = await _rows(DocumentPage, document_id)
    assert (page.content, page.screenshot) == ("second", "b")


async def test_a_chunk_written_twice_keeps_its_id_so_its_vector_is_replaced_not_doubled(client, search_index):
    _, document_id = await _collection_with_document()
    url = f"/api/internal/documents/{document_id}/chunks"
    body = {"index": 0, "text": "chunk", "token_count": 3, "embedding": [0.1, 0.2]}

    await client.post(url, headers=_headers(), json=body)
    await client.post(url, headers=_headers(), json={**body, "text": "chunk again"})

    (chunk,) = await _rows(Chunk, document_id)
    assert chunk.text == "chunk again"
    assert search_index["chunks_upserted"] == [chunk.id, chunk.id]


async def test_a_whole_document_written_twice_has_the_same_pages_and_chunks(client, search_index):
    _, document_id = await _collection_with_document()
    for _ in range(2):
        for number in (1, 2, 3):
            await client.post(
                f"/api/internal/documents/{document_id}/pages",
                headers=_headers(),
                json={"page_number": number, "content": f"page {number}"},
            )
        for index in range(4):
            await client.post(
                f"/api/internal/documents/{document_id}/chunks",
                headers=_headers(),
                json={"index": index, "text": f"chunk {index}", "token_count": 2},
            )

    assert sorted(page.page_number for page in await _rows(DocumentPage, document_id)) == [1, 2, 3]
    assert sorted(chunk.index for chunk in await _rows(Chunk, document_id)) == [0, 1, 2, 3]


async def test_pruning_drops_what_a_longer_run_left_after_the_last_page(client, search_index):
    _, document_id = await _collection_with_document()
    for number in (1, 2, 3):
        await client.post(
            f"/api/internal/documents/{document_id}/pages",
            headers=_headers(),
            json={"page_number": number, "content": "x", "screenshot": f"shot-{number}"},
        )

    response = await client.post(
        f"/api/internal/documents/{document_id}/pages/prune", headers=_headers(), json={"keep": 2}
    )

    assert response.status_code == 200
    assert sorted(page.page_number for page in await _rows(DocumentPage, document_id)) == [1, 2]
    assert search_index["objects_deleted"] == ["shot-3"]


async def test_pruning_drops_the_chunks_after_the_last_with_their_vectors(client, search_index):
    _, document_id = await _collection_with_document()
    for index in range(3):
        await client.post(
            f"/api/internal/documents/{document_id}/chunks",
            headers=_headers(),
            json={"index": index, "text": "x", "token_count": 1},
        )
    dropped = [chunk.id for chunk in await _rows(Chunk, document_id) if chunk.index == 2]

    response = await client.post(
        f"/api/internal/documents/{document_id}/chunks/prune", headers=_headers(), json={"keep": 2}
    )

    assert response.status_code == 200
    assert sorted(chunk.index for chunk in await _rows(Chunk, document_id)) == [0, 1]
    assert search_index["chunks_deleted"] == dropped


@pytest.mark.parametrize("what", ["pages", "chunks"])
async def test_pruning_an_unknown_document(client, search_index, what):
    response = await client.post(
        f"/api/internal/documents/{uuid.uuid4()}/{what}/prune", headers=_headers(), json={"keep": 1}
    )

    assert response.status_code == 404


# -- what is derived from a document goes with it -----------------------------------------------


async def _derive_from(collection_id, document_id):
    """A generated pair (one a person validated), a manual pair, and entities with a relation: Acme is
    also mentioned in another document of the collection, Alice only here."""
    async with async_session_factory() as session:
        other = Document(collection_id=collection_id, name="memo.pdf", type="file", storage_key="m")
        session.add(other)
        await session.flush()
        session.add_all(
            [
                QaPair(
                    collection_id=collection_id,
                    document_id=document_id,
                    question="Generated?",
                    answer="Yes.",
                    origin=QaOrigin.GENERATED,
                    generation_key="window:1-2",
                ),
                QaPair(
                    collection_id=collection_id,
                    document_id=document_id,
                    question="Validated?",
                    answer="Yes.",
                    origin=QaOrigin.GENERATED,
                    validated=True,
                    generation_key="window:1-2",
                ),
                QaPair(
                    collection_id=collection_id,
                    document_id=document_id,
                    question="Manual?",
                    answer="Yes.",
                    origin=QaOrigin.MANUAL,
                    validated=True,
                ),
            ]
        )
        entities = EntityRepository(session)
        await entities.replace_window(
            collection_id,
            document_id,
            "pages:1-2",
            [("Acme Corp", "organisation", 2), ("Alice", "personne", 1)],
            [("Alice", "Acme Corp", "works_at")],
        )
        await entities.replace_window(collection_id, other.id, "pages:1-2", [("Acme Corp", "organisation", 1)], [])
        await session.commit()
        return other.id


async def _questions(collection_id) -> dict[str, uuid.UUID | None]:
    async with async_session_factory() as session:
        result = await session.execute(select(QaPair).where(QaPair.collection_id == collection_id))
        return {pair.question: pair.document_id for pair in result.scalars().all()}


async def _entity_mentions(collection_id) -> dict[str, int]:
    async with async_session_factory() as session:
        result = await session.execute(select(Entity).where(Entity.collection_id == collection_id))
        return {entity.name: entity.mentions for entity in result.scalars().all()}


async def test_deleting_a_document_deletes_what_was_generated_from_it(client, search_index):
    collection_id, document_id = await _collection_with_document()
    other_id = await _derive_from(collection_id, document_id)
    removed = [pair.id for pair in await _all_generated(collection_id)]

    async with async_session_factory() as session:
        await DocumentUploadService(session).delete_document(collection_id, USER, document_id)

    # Generated pairs go, the validated one too - what it answered from is gone. A manual pair stays,
    # as it always did, with no document.
    assert await _questions(collection_id) == {"Manual?": None}
    assert sorted(search_index["qa_deleted"]) == sorted(removed)
    # Acme is still mentioned by the other document, once; Alice by nothing, so she goes with her relation.
    assert await _entity_mentions(collection_id) == {"Acme Corp": 1}
    async with async_session_factory() as session:
        assert (await session.execute(select(Relation))).scalars().all() == []
        assert [link.document_id for link in (await session.execute(select(EntityDocument))).scalars().all()] == [
            other_id
        ]


async def _all_generated(collection_id):
    async with async_session_factory() as session:
        result = await session.execute(
            select(QaPair).where(QaPair.collection_id == collection_id, QaPair.origin == QaOrigin.GENERATED)
        )
        return result.scalars().all()


async def test_reprocessing_a_document_regenerates_what_it_derived_but_keeps_validated_pairs(client, search_index):
    collection_id, document_id = await _collection_with_document()
    await _derive_from(collection_id, document_id)
    async with async_session_factory() as session:
        document = await session.get(Document, document_id)
        with patch(
            "app.services.document_upload_service.enqueue_process_document",
            side_effect=lambda _id, **_: str(uuid.uuid4()),
        ):
            await DocumentUploadService(session).reprocess(document, "dev-user")

    # The unvalidated generated pair goes, to be generated again; a person's work stays.
    assert set(await _questions(collection_id)) == {"Validated?", "Manual?"}
    assert await _entity_mentions(collection_id) == {"Acme Corp": 1}
    assert len(search_index["qa_deleted"]) == 1
    async with async_session_factory() as session:
        assert (await session.get(Document, document_id)).status == DocumentStatus.PENDING


async def test_regenerating_after_a_reprocess_gives_the_same_state_as_the_first_time(client, search_index):
    collection_id, document_id = await _collection_with_document()
    await _derive_from(collection_id, document_id)
    before = await _entity_mentions(collection_id)
    async with async_session_factory() as session:
        document = await session.get(Document, document_id)
        with patch(
            "app.services.document_upload_service.enqueue_process_document",
            side_effect=lambda _id, **_: str(uuid.uuid4()),
        ):
            await DocumentUploadService(session).reprocess(document, "dev-user")
        # What the pipeline then runs again.
        await EntityRepository(session).replace_window(
            collection_id,
            document_id,
            "pages:1-2",
            [("Acme Corp", "organisation", 2), ("Alice", "personne", 1)],
            [("Alice", "Acme Corp", "works_at")],
        )
        await session.commit()

    assert await _entity_mentions(collection_id) == before


async def test_deleting_a_collection_still_cascades(client, search_index):
    collection_id, document_id = await _collection_with_document()
    await _derive_from(collection_id, document_id)
    async with async_session_factory() as session:
        await session.execute(update(Document).where(Document.id == document_id).values(status=DocumentStatus.INDEXED))
        await session.execute(delete(Collection).where(Collection.id == collection_id))
        await session.commit()

    async with async_session_factory() as session:
        assert (await session.execute(select(QaPair))).scalars().all() == []
        assert (await session.execute(select(Entity))).scalars().all() == []
