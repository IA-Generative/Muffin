import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection
from app.models.document import Document, DocumentPage, DocumentTag
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
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id",
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
        "app.services.document_upload_service.enqueue_process_document",
        return_value="celery-task-id",
    ) as mock_enqueue:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/url",
            json={"url": "https://example.com"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "https://example.com"
    assert body["type"] == "url"
    mock_enqueue.assert_called_once_with(body["id"])


async def test_list_documents(client):
    collection_id = await _create_collection(client)
    with patch(
        "app.services.document_upload_service.enqueue_process_document",
        return_value="celery-task-id",
    ):
        await client.post(
            f"/api/collections/{collection_id}/documents/url",
            json={"url": "https://example.com"},
        )

    response = await client.get(f"/api/collections/{collection_id}/documents")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_create_document_for_unknown_collection_returns_404(client):
    with patch(
        "app.services.document_upload_service.enqueue_process_document",
        return_value="celery-task-id",
    ):
        response = await client.post(
            f"/api/collections/{uuid.uuid4()}/documents/url",
            json={"url": "https://example.com"},
        )
    assert response.status_code == 404


async def test_get_document_returns_detail_with_tags_and_page_count(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id",
        ),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    async with async_session_factory() as session:
        document = await session.get(Document, uuid.UUID(created["id"]))
        document.summary = "A short summary."
        session.add(DocumentTag(document_id=document.id, tag="hr"))
        session.add(DocumentPage(document_id=document.id, page_number=1, content="page one"))
        session.add(DocumentPage(document_id=document.id, page_number=2, content="page two"))
        await session.commit()

    response = await client.get(f"/api/collections/{collection_id}/documents/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "A short summary."
    assert body["tags"] == ["hr"]
    assert body["page_count"] == 2


async def test_get_unknown_document_returns_404(client):
    collection_id = await _create_collection(client)
    response = await client.get(f"/api/collections/{collection_id}/documents/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_document_pages_paginated_with_screenshot_urls(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id",
        ),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    async with async_session_factory() as session:
        session.add(
            DocumentPage(
                document_id=created["id"],
                page_number=1,
                content="page one",
                screenshot="p1.png",
            )
        )
        session.add(DocumentPage(document_id=created["id"], page_number=2, content="page two"))
        await session.commit()

    response = await client.get(
        f"/api/collections/{collection_id}/documents/{created['id']}/pages",
        params={"page_size": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["page_number"] == 1
    # A path on this backend, never a direct/public storage URL - see get_page_screenshot.
    assert body["items"][0]["screenshot_url"] == (
        f"/api/collections/{collection_id}/documents/{created['id']}/pages/1/screenshot"
    )


async def test_get_page_screenshot_streams_through_the_backend(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id",
        ),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    async with async_session_factory() as session:
        session.add(
            DocumentPage(
                document_id=created["id"],
                page_number=1,
                content="page one",
                screenshot="p1.png",
            )
        )
        await session.commit()

    with patch(
        "app.services.document_upload_service.storage.get_object",
        return_value=(b"fake-png-bytes", "image/png"),
    ) as mock_get_object:
        response = await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/pages/1/screenshot")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"fake-png-bytes"
    mock_get_object.assert_called_once_with("p1.png")


async def test_get_page_screenshot_for_page_without_one_returns_404(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id",
        ),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    async with async_session_factory() as session:
        session.add(DocumentPage(document_id=created["id"], page_number=1, content="page one"))
        await session.commit()

    response = await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/pages/1/screenshot")
    assert response.status_code == 404


async def test_delete_document_removes_its_rustfs_objects(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id",
        ),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    with (
        patch("app.services.document_upload_service.storage.delete_objects") as mock_delete,
        patch("app.services.document_upload_service.vector_store.delete_document_embeddings") as mock_delete_vectors,
    ):
        response = await client.delete(f"/api/collections/{collection_id}/documents/{created['id']}")

    assert response.status_code == 204
    mock_delete.assert_called_once()
    mock_delete_vectors.assert_called_once()

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
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id-1",
        ),
    ):
        created = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("report.pdf", b"data", "application/pdf")},
            )
        ).json()

    async with async_session_factory() as session:
        session.add(
            DocumentPage(
                document_id=created["id"],
                page_number=1,
                content="old",
                screenshot="old.png",
            )
        )
        session.add(Chunk(document_id=created["id"], index=0, text="old chunk", token_count=2))
        await session.commit()

    with (
        patch("app.services.document_upload_service.storage.delete_objects") as mock_delete,
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-task-id-2",
        ) as mock_enqueue,
        patch("app.services.document_upload_service.vector_store.delete_document_embeddings"),
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


async def test_document_entities_and_relations_are_scoped_to_their_own_document(client):
    from app.repositories.entity_repository import EntityRepository

    collection_id = await _create_collection(client)
    async with async_session_factory() as session:
        report = Document(collection_id=collection_id, name="report.pdf", type="url")
        memo = Document(collection_id=collection_id, name="memo.pdf", type="url")
        session.add_all([report, memo])
        await session.flush()
        report_id, memo_id = report.id, memo.id

        entities = EntityRepository(session)
        # "Acme Corp" is mentioned in both documents - collection-wide it's one Entity with
        # mentions=2, but each document's own view must only ever show its own mention(s).
        acme = await entities.upsert(collection_id, report_id, "Acme Corp", "organisation", 1)
        await entities.upsert(collection_id, memo_id, "Acme Corp", "organisation", 1)
        alice = await entities.upsert(collection_id, report_id, "Alice", "personne", 1)
        await entities.create_relation(collection_id, report_id, alice.id, acme.id, "works_at")
        await session.commit()

    report_entities = (await client.get(f"/api/collections/{collection_id}/documents/{report_id}/entities")).json()
    memo_entities = (await client.get(f"/api/collections/{collection_id}/documents/{memo_id}/entities")).json()
    report_relations = (await client.get(f"/api/collections/{collection_id}/documents/{report_id}/relations")).json()
    memo_relations = (await client.get(f"/api/collections/{collection_id}/documents/{memo_id}/relations")).json()

    assert {e["name"] for e in report_entities} == {"Acme Corp", "Alice"}
    assert {e["name"] for e in memo_entities} == {"Acme Corp"}
    assert len(report_relations) == 1
    assert report_relations[0]["type"] == "works_at"
    assert memo_relations == []
