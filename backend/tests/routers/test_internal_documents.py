import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    # See tests/routers/test_collections.py for why this isn't the sync TestClient.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _create_document(
    client, *, doc_type: str = "file", name: str = "report.pdf", storage_key: str | None = "abc"
):
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()

        from app.models.document import Document

        document = Document(collection_id=collection.id, name=name, type=doc_type, storage_key=storage_key)
        session.add(document)
        await session.commit()
        return document.id


def _headers(api_key: str = API_KEY) -> dict[str, str]:
    return {"X-API-Key": api_key}


async def test_get_document_requires_api_key(client):
    document_id = await _create_document(client)
    assert (await client.get(f"/api/internal/documents/{document_id}")).status_code == 401
    assert (await client.get(f"/api/internal/documents/{document_id}", headers=_headers("wrong"))).status_code == 401


async def test_get_document_returns_metadata(client):
    document_id = await _create_document(client, doc_type="file", name="report.pdf", storage_key="docs/report.pdf")

    response = await client.get(f"/api/internal/documents/{document_id}", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "report.pdf"
    assert body["type"] == "file"
    assert body["storage_key"] == "docs/report.pdf"
    assert body["status"] == "pending"


async def test_get_document_not_found(client):
    response = await client.get(f"/api/internal/documents/{uuid.uuid4()}", headers=_headers())
    assert response.status_code == 404


async def test_update_document_status(client):
    document_id = await _create_document(client)

    response = await client.patch(
        f"/api/internal/documents/{document_id}/status",
        headers=_headers(),
        json={"status": "indexed", "progress": 100},
    )

    assert response.status_code == 200
    body = (await client.get(f"/api/internal/documents/{document_id}", headers=_headers())).json()
    assert body["status"] == "indexed"


async def test_create_document_page_and_chunk_with_extras(client):
    document_id = await _create_document(client)

    page_response = await client.post(
        f"/api/internal/documents/{document_id}/pages",
        headers=_headers(),
        json={"page_number": 1, "content": "Hello world", "screenshot": "screens/page-1.png"},
    )
    assert page_response.status_code == 201

    chunk_response = await client.post(
        f"/api/internal/documents/{document_id}/chunks",
        headers=_headers(),
        json={
            "index": 0,
            "text": "Hello world",
            "token_count": 2,
            "extras": {"bbox": {"x": 0, "y": 0, "width": 100, "height": 20}, "kind": "paragraph"},
        },
    )
    assert chunk_response.status_code == 201

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.chunk import Chunk
        from app.models.document import DocumentPage

        pages = (
            (await session.execute(select(DocumentPage).where(DocumentPage.document_id == document_id))).scalars().all()
        )
        chunks = (await session.execute(select(Chunk).where(Chunk.document_id == document_id))).scalars().all()

    assert len(pages) == 1
    assert pages[0].screenshot == "screens/page-1.png"
    assert len(chunks) == 1
    assert chunks[0].extras == {"bbox": {"x": 0, "y": 0, "width": 100, "height": 20}, "kind": "paragraph"}


async def test_create_document_chunk_with_embedding_upserts_into_meilisearch(client, monkeypatch):
    from app.services import vector_store

    document_id = await _create_document(client)
    upserted: list[tuple] = []
    monkeypatch.setattr(vector_store, "upsert_chunk_embedding", lambda *args: upserted.append(args))

    response = await client.post(
        f"/api/internal/documents/{document_id}/chunks",
        headers=_headers(),
        json={"index": 0, "text": "Hello world", "token_count": 2, "embedding": [0.1, 0.2, 0.3]},
    )

    assert response.status_code == 201
    assert len(upserted) == 1
    collection_id, chunk_id, embedding, text = upserted[0]
    assert embedding == [0.1, 0.2, 0.3]
    assert text == "Hello world"

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.chunk import Chunk
        from app.models.document import Document

        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
        chunk = (await session.execute(select(Chunk).where(Chunk.document_id == document_id))).scalar_one()

    assert collection_id == document.collection_id
    assert chunk_id == chunk.id


async def test_create_document_chunk_without_embedding_does_not_touch_meilisearch(client, monkeypatch):
    from app.services import vector_store

    document_id = await _create_document(client)
    upserted: list[tuple] = []
    monkeypatch.setattr(vector_store, "upsert_chunk_embedding", lambda *args: upserted.append(args))

    response = await client.post(
        f"/api/internal/documents/{document_id}/chunks",
        headers=_headers(),
        json={"index": 0, "text": "Hello world", "token_count": 2},
    )

    assert response.status_code == 201
    assert upserted == []


async def test_list_document_pages(client):
    document_id = await _create_document(client)
    await client.post(
        f"/api/internal/documents/{document_id}/pages",
        headers=_headers(),
        json={"page_number": 1, "content": "Page one"},
    )
    await client.post(
        f"/api/internal/documents/{document_id}/pages",
        headers=_headers(),
        json={"page_number": 2, "content": "Page two"},
    )

    response = await client.get(f"/api/internal/documents/{document_id}/pages", headers=_headers())

    assert response.status_code == 200
    assert response.json() == [
        {"page_number": 1, "content": "Page one"},
        {"page_number": 2, "content": "Page two"},
    ]


async def test_update_document_summary(client):
    document_id = await _create_document(client)

    response = await client.patch(
        f"/api/internal/documents/{document_id}/summary", headers=_headers(), json={"summary": "A short summary."}
    )

    assert response.status_code == 200
    body = (await client.get(f"/api/internal/documents/{document_id}", headers=_headers())).json()
    assert body["summary"] == "A short summary."


async def test_update_document_error_does_not_clobber_summary(client):
    document_id = await _create_document(client)
    await client.patch(
        f"/api/internal/documents/{document_id}/summary", headers=_headers(), json={"summary": "Kept summary."}
    )

    response = await client.patch(
        f"/api/internal/documents/{document_id}/error", headers=_headers(), json={"error": "Boom"}
    )

    assert response.status_code == 200
    body = (await client.get(f"/api/internal/documents/{document_id}", headers=_headers())).json()
    assert body["summary"] == "Kept summary."


async def _create_temporary_collection_document(
    *, owner_id: str = "dev-user", summary: str | None = "A summary."
) -> uuid.UUID:
    async with async_session_factory() as session:
        from app.models.document import Document

        collection = Collection(
            owner_id=owner_id, name="Fichiers de la conversation", description="", is_temporary=True
        )
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(
            collection_id=collection.id, name="notes.txt", type="file", storage_key="k", summary=summary
        )
        session.add(document)
        await session.commit()
        return document.id


async def test_suggest_filing_not_found(client):
    response = await client.post(f"/api/internal/documents/{uuid.uuid4()}/suggest-filing", headers=_headers())
    assert response.status_code == 404


async def test_suggest_filing_skips_non_temporary_collection(client, monkeypatch):
    from app.services import document_service

    document_id = await _create_document(client, storage_key="k")
    calls = []
    monkeypatch.setattr(document_service, "default_embedding_model", lambda db: calls.append(1))

    response = await client.post(f"/api/internal/documents/{document_id}/suggest-filing", headers=_headers())

    assert response.status_code == 200
    assert calls == []  # never even tried - not a conversation file


async def test_suggest_filing_skips_document_without_summary(client, monkeypatch):
    from app.services import document_service

    document_id = await _create_temporary_collection_document(summary=None)
    calls = []
    monkeypatch.setattr(document_service, "default_embedding_model", lambda db: calls.append(1))

    response = await client.post(f"/api/internal/documents/{document_id}/suggest-filing", headers=_headers())

    assert response.status_code == 200
    assert calls == []


async def test_suggest_filing_sets_the_best_matching_owned_collection(client, monkeypatch):
    from app.services import document_service

    document_id = await _create_temporary_collection_document(owner_id="dev-user")
    async with async_session_factory() as session:
        target = Collection(owner_id="dev-user", name="Rapports", description="Rapports trimestriels.")
        target.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(target)
        await session.commit()
        target_id = target.id

    async def fake_default_embedding_model(db):
        return "text-embedding-3-small"

    async def fake_embed_text(model, text):
        return [0.1, 0.2]

    monkeypatch.setattr(document_service, "default_embedding_model", fake_default_embedding_model)
    monkeypatch.setattr(document_service, "embed_text", fake_embed_text)
    monkeypatch.setattr(
        document_service.vector_store,
        "search_collections",
        lambda query, query_embedding, collection_ids, limit: [(target_id, 0.83)],
    )

    response = await client.post(f"/api/internal/documents/{document_id}/suggest-filing", headers=_headers())

    assert response.status_code == 200
    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.document import Document

        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
    assert document.suggested_collection_id == target_id
    assert document.suggested_collection_score == 0.83
    assert document.filing_candidates == [
        {
            "collection_id": str(target_id),
            "collection_name": "Rapports",
            "collection_description": "Rapports trimestriels.",
            "score": 0.83,
        }
    ]


async def test_suggest_filing_keeps_the_top_k_candidates_in_rank_order(client, monkeypatch):
    from app.services import document_service

    document_id = await _create_temporary_collection_document(owner_id="dev-user")
    async with async_session_factory() as session:
        first = Collection(owner_id="dev-user", name="Rapports", description="Rapports trimestriels.")
        first.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        second = Collection(owner_id="dev-user", name="Comptabilité", description="Bilans comptables.")
        second.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add_all([first, second])
        await session.commit()
        first_id, second_id = first.id, second.id

    async def fake_default_embedding_model(db):
        return "text-embedding-3-small"

    async def fake_embed_text(model, text):
        return [0.1, 0.2]

    monkeypatch.setattr(document_service, "default_embedding_model", fake_default_embedding_model)
    monkeypatch.setattr(document_service, "embed_text", fake_embed_text)
    monkeypatch.setattr(
        document_service.vector_store,
        "search_collections",
        lambda query, query_embedding, collection_ids, limit: [(first_id, 0.9), (second_id, 0.6)],
    )

    response = await client.post(f"/api/internal/documents/{document_id}/suggest-filing", headers=_headers())

    assert response.status_code == 200
    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.document import Document

        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
    # Top-1 mirrors the first (highest-ranked) candidate.
    assert document.suggested_collection_id == first_id
    assert document.suggested_collection_score == 0.9
    assert [c["collection_id"] for c in document.filing_candidates] == [str(first_id), str(second_id)]
    assert [c["score"] for c in document.filing_candidates] == [0.9, 0.6]


async def test_suggest_filing_no_embedding_model_configured_is_a_no_op(client, monkeypatch):
    from app.services import document_service

    document_id = await _create_temporary_collection_document()

    async def fake_default_embedding_model(db):
        return None

    monkeypatch.setattr(document_service, "default_embedding_model", fake_default_embedding_model)

    response = await client.post(f"/api/internal/documents/{document_id}/suggest-filing", headers=_headers())

    assert response.status_code == 200
    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.document import Document

        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
    assert document.suggested_collection_id is None


async def test_replace_document_tags(client):
    document_id = await _create_document(client)

    response = await client.put(
        f"/api/internal/documents/{document_id}/tags", headers=_headers(), json={"tags": ["invoice", "2024"]}
    )
    assert response.status_code == 200

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.document import DocumentTag

        tags = (
            (await session.execute(select(DocumentTag).where(DocumentTag.document_id == document_id))).scalars().all()
        )
    assert sorted(tag.tag for tag in tags) == ["2024", "invoice"]
