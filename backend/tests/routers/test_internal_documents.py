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
