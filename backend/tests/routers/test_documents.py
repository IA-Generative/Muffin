import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection
from app.models.document import DocumentPage
from app.models.task import Task


@pytest.fixture
async def client():
    # See tests/routers/test_collections.py for why this isn't the sync TestClient.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        # Task rows aren't cascade-deleted with their collection/document
        # (ondelete="SET NULL" - see app/models/task.py), so they'd otherwise
        # pile up across test runs and collide on celery_task_id's unique index.
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


async def _create_collection(client) -> str:
    return (await client.post("/api/collections")).json()["id"]


async def test_create_file_document_uploads_and_queues_processing(client):
    collection_id = await _create_collection(client)

    with (
        patch("app.services.document_upload_service.storage.put_object") as mock_put,
        patch(
            "app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id"
        ) as mock_enqueue,
    ):
        response = await client.post(
            f"/api/collections/{collection_id}/documents/file",
            files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "report.pdf"
    assert body["type"] == "file"
    assert body["status"] == "pending"

    mock_put.assert_called_once()
    key, data = mock_put.call_args.args[:2]
    assert key.endswith("-report.pdf")
    assert data == b"%PDF-1.4 fake"
    mock_enqueue.assert_called_once_with(body["id"])


async def test_create_url_document_queues_processing(client):
    collection_id = await _create_collection(client)

    with patch(
        "app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id"
    ) as mock_enqueue:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/url", json={"url": "https://example.com"}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "https://example.com"
    assert body["type"] == "url"
    mock_enqueue.assert_called_once_with(body["id"])


async def test_list_documents(client):
    collection_id = await _create_collection(client)
    with patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id"):
        await client.post(f"/api/collections/{collection_id}/documents/url", json={"url": "https://example.com"})

    response = await client.get(f"/api/collections/{collection_id}/documents")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_create_document_for_unknown_collection_returns_404(client):
    with patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id"):
        response = await client.post(
            f"/api/collections/{uuid.uuid4()}/documents/url", json={"url": "https://example.com"}
        )
    assert response.status_code == 404


async def test_delete_document_removes_its_rustfs_objects(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id"),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    with patch("app.services.document_upload_service.storage.delete_objects") as mock_delete:
        response = await client.delete(f"/api/collections/{collection_id}/documents/{created['id']}")

    assert response.status_code == 204
    mock_delete.assert_called_once()

    remaining = await client.get(f"/api/collections/{collection_id}/documents")
    assert remaining.json() == []


async def test_delete_unknown_document_returns_404(client):
    collection_id = await _create_collection(client)
    response = await client.delete(f"/api/collections/{collection_id}/documents/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_reindex_resets_status_and_requeues(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id-1"),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    async with async_session_factory() as session:
        session.add(DocumentPage(document_id=created["id"], page_number=1, content="old", screenshot="old.png"))
        session.add(Chunk(document_id=created["id"], index=0, text="old chunk", token_count=2))
        await session.commit()

    with (
        patch("app.services.document_upload_service.storage.delete_objects") as mock_delete,
        patch(
            "app.services.document_upload_service.enqueue_process_document", return_value="celery-task-id-2"
        ) as mock_enqueue,
    ):
        response = await client.post(f"/api/collections/{collection_id}/documents/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["status"] == "pending"
    assert body[0]["progress"] == 0
    mock_enqueue.assert_called_once_with(created["id"])
    mock_delete.assert_called_once_with(["old.png"])

    async with async_session_factory() as session:
        pages = (await session.execute(select(DocumentPage))).scalars().all()
        chunks = (await session.execute(select(Chunk))).scalars().all()
    assert pages == []
    assert chunks == []
