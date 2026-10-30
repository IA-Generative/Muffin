"""The files copied from Open WebUI (#453): the row, its text on one page, and the chunks its vector store holds."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection
from app.models.document import Document, DocumentPage, DocumentStatus
from app.models.index_rebuild import IndexRebuild, IndexRebuildStatus
from app.routers import internal_document_sync

API_KEY = "test-worker-key"
HEADERS = {"X-API-Key": API_KEY}
FILE = "kb1/file1"


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        await async_client.put(
            "/api/internal/synced-collections/owui/kb1",
            headers=HEADERS,
            json={"name": "Procédures", "owner_id": "sub-owner", "embedding_model": "bge"},
        )
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


def _chunk(index: int, chunk_id: uuid.UUID | None = None, text: str | None = None) -> dict:
    return {"id": str(chunk_id or uuid.uuid4()), "index": index, "text": text or f"chunk {index}", "token_count": 3}


async def _put(client, external_id=FILE, **overrides):
    body = {
        "collection_external_id": "kb1",
        "name": "test.pdf",
        "storage_key": "s3://owui-files/id_test.pdf",
        "content_hash": "abc",
        "text": "The whole text.",
        "chunks": [_chunk(0), _chunk(1)],
        **overrides,
    }
    return await client.put(f"/api/internal/synced-documents/owui/{external_id}", headers=HEADERS, json=body)


async def _chunks(document_id) -> list[tuple[int, str]]:
    async with async_session_factory() as session:
        rows = await session.scalars(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.index))
        return [(chunk.index, chunk.text) for chunk in rows]


async def test_the_worker_key_is_required(client):
    assert (await client.put("/api/internal/synced-documents/owui/kb1/f", json={})).status_code == 401


async def test_a_file_is_created_indexed_with_its_chunks_and_its_text_on_one_page(client):
    response = await _put(client)

    assert response.status_code == 200
    body = response.json()
    assert (body["created"], body["chunks_written"], body["chunks_removed"]) == (True, 2, 0)
    async with async_session_factory() as session:
        document = await session.get(Document, body["id"])
        pages = list(await session.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id)))
    assert (document.source, document.external_id) == ("owui", FILE)
    assert (document.status, document.progress) == (DocumentStatus.INDEXED, 100)
    assert document.storage_key == "s3://owui-files/id_test.pdf"
    assert [(page.page_number, page.content) for page in pages] == [(1, "The whole text.")]
    assert await _chunks(document.id) == [(0, "chunk 0"), (1, "chunk 1")]


async def test_a_collection_that_is_not_synchronised_yet_is_a_conflict(client):
    assert (await _put(client, collection_external_id="nope")).status_code == 409


async def test_syncing_again_with_the_same_chunks_changes_nothing(client):
    chunks = [_chunk(0), _chunk(1)]
    first = (await _put(client, chunks=chunks)).json()
    second = (await _put(client, chunks=chunks)).json()

    assert second["id"] == first["id"]
    assert (second["created"], second["chunks_removed"]) == (False, 0)
    assert await _chunks(first["id"]) == [(0, "chunk 0"), (1, "chunk 1")]


async def test_a_file_cut_again_replaces_its_chunks(client):
    kept = uuid.uuid4()
    first = (await _put(client, chunks=[_chunk(0, kept), _chunk(1)])).json()
    second = (await _put(client, chunks=[_chunk(0, kept, "edited"), _chunk(1), _chunk(2)])).json()

    assert second["chunks_removed"] == 1
    assert [text for _, text in await _chunks(first["id"])][0] == "edited"
    assert len(await _chunks(first["id"])) == 3


async def test_a_chunk_that_is_gone_is_removed_even_if_another_takes_its_place(client):
    first = (await _put(client, chunks=[_chunk(0, text="old")])).json()
    await _put(client, chunks=[_chunk(0, text="new")])

    assert await _chunks(first["id"]) == [(0, "new")]


async def test_the_same_file_in_two_collections_is_two_documents(client):
    await client.put(
        "/api/internal/synced-collections/owui/kb2",
        headers=HEADERS,
        json={"name": "Autre", "owner_id": "sub-owner", "embedding_model": "bge"},
    )
    first = (await _put(client, "kb1/file1")).json()
    second = (await _put(client, "kb2/file1", collection_external_id="kb2")).json()

    assert first["id"] != second["id"]


async def test_the_files_made_in_muffin_are_not_the_synchronisations_to_write(client):
    response = await client.put(
        "/api/internal/synced-documents/muffin/kb1/f",
        headers=HEADERS,
        json={"collection_external_id": "kb1", "name": "x", "storage_key": "k"},
    )
    assert response.status_code == 400


async def test_a_file_gone_from_the_other_system_is_dropped_with_its_chunks(client):
    document_id = (await _put(client)).json()["id"]

    assert (await client.get("/api/internal/synced-documents/owui", headers=HEADERS)).json() == [FILE]
    assert (await client.delete(f"/api/internal/synced-documents/owui/{FILE}", headers=HEADERS)).status_code == 204

    assert (await client.get("/api/internal/synced-documents/owui", headers=HEADERS)).json() == []
    assert await _chunks(document_id) == []
    assert (await client.delete(f"/api/internal/synced-documents/owui/{FILE}", headers=HEADERS)).status_code == 404


async def _set_summary(document_id, summary="A summary."):
    async with async_session_factory() as session:
        document = await session.get(Document, document_id)
        document.summary = summary
        await session.commit()


async def test_a_new_file_is_due_a_summary_in_its_collection(client):
    body = (await _put(client)).json()

    assert body["summary_due"] is True
    async with async_session_factory() as session:
        assert body["collection_id"] == str((await session.get(Document, body["id"])).collection_id)


async def test_a_file_with_a_summary_that_did_not_change_is_not_due_another(client):
    document_id = (await _put(client)).json()["id"]
    await _set_summary(document_id)

    assert (await _put(client)).json()["summary_due"] is False


async def test_a_file_that_still_has_no_summary_is_due_one_again(client):
    await _put(client)

    assert (await _put(client)).json()["summary_due"] is True


async def test_a_file_whose_content_changed_loses_its_summary_and_is_due_a_new_one(client, monkeypatch):
    dropped = []
    monkeypatch.setattr(
        internal_document_sync.vector_store,
        "delete_document_embeddings",
        lambda collection_id, document_id, chunk_ids: dropped.append((document_id, chunk_ids)),
    )
    document_id = (await _put(client)).json()["id"]
    await _set_summary(document_id)

    body = (await _put(client, content_hash="def")).json()

    assert body["summary_due"] is True
    assert [(str(identifier), chunk_ids) for identifier, chunk_ids in dropped] == [(document_id, [])]
    async with async_session_factory() as session:
        assert (await session.get(Document, document_id)).summary is None


async def test_the_summary_point_of_a_file_gone_is_removed(client, monkeypatch):
    dropped = []
    monkeypatch.setattr(
        internal_document_sync.vector_store,
        "delete_document_embeddings",
        lambda collection_id, document_id, chunk_ids: dropped.append(document_id),
    )
    document_id = (await _put(client)).json()["id"]

    await client.delete(f"/api/internal/synced-documents/owui/{FILE}", headers=HEADERS)

    assert [str(identifier) for identifier in dropped] == [document_id]


# -- a collection Muffin took over, or is taking over (#462) ----------------------------------------------


@pytest.fixture(params=["adopted", "being taken over"])
async def held(client, request):
    """A copy with one file, that Muffin has taken over or is rebuilding the index of to do so."""
    document_id = (await _put(client)).json()["id"]
    async with async_session_factory() as session:
        collection_id = (await session.get(Document, document_id)).collection_id
        if request.param == "adopted":
            (await session.get(Collection, collection_id)).adopted_at = datetime.now(UTC)
        else:
            session.add(
                IndexRebuild(
                    collection_id=collection_id,
                    status=IndexRebuildStatus.BUILDING,
                    target_model="m",
                    previous_model="m",
                    requested_by="admin",
                    adopts=True,
                )
            )
        await session.commit()
    return document_id


async def test_the_synchronisation_leaves_the_files_of_a_collection_muffin_took_over_as_they_are(client, held):
    response = await _put(client, name="renamed.pdf", text="Another text.", chunks=[_chunk(0, text="other")])

    body = response.json()
    assert (response.status_code, body["skipped"], body["created"], str(body["id"])) == (200, True, False, str(held))
    async with async_session_factory() as session:
        document = await session.get(Document, held)
        pages = list(await session.scalars(select(DocumentPage).where(DocumentPage.document_id == held)))
    assert document.name == "test.pdf" and [page.content for page in pages] == ["The whole text."]
    assert await _chunks(held) == [(0, "chunk 0"), (1, "chunk 1")]


async def test_a_new_file_is_not_created_in_a_collection_muffin_took_over(client, held):
    body = (await _put(client, "kb1/file2")).json()

    assert (body["skipped"], body["id"]) == (True, None)
    assert (await client.get("/api/internal/synced-documents/owui", headers=HEADERS)).json() == []


async def test_the_files_of_a_collection_muffin_took_over_are_not_listed_nor_deleted(client, held):
    assert (await client.get("/api/internal/synced-documents/owui", headers=HEADERS)).json() == []

    response = await client.delete(f"/api/internal/synced-documents/owui/{FILE}", headers=HEADERS)

    assert response.status_code == 404
    async with async_session_factory() as session:
        assert await session.get(Document, held) is not None
