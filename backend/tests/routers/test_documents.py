import uuid
from unittest.mock import ANY, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection
from app.models.document import Document, DocumentPage, DocumentStatus, DocumentTag
from app.models.task import Task
from app.services.document_upload_service import DocumentUploadService
from tests.routers.test_collections import _as_user


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
    stored = {}

    with (
        # Streamed from the upload's spooled file, never read whole into memory.
        patch(
            "app.services.document_upload_service.storage.upload_fileobj",
            side_effect=lambda key, fileobj, content_type: stored.__setitem__(key, fileobj.read()),
        ),
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

    [(key, data)] = stored.items()
    assert key.endswith("-report.pdf")
    assert data == b"%PDF-1.4 fake"
    mock_enqueue.assert_called_once_with(body["id"], bulk=False, task_id=ANY)


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
    mock_enqueue.assert_called_once_with(body["id"], bulk=False, task_id=ANY)


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
        patch("app.services.document_upload_service.storage.upload_fileobj"),
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
        patch("app.services.document_upload_service.storage.upload_fileobj"),
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
        patch("app.services.document_upload_service.storage.upload_fileobj"),
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
        patch("app.services.document_upload_service.storage.upload_fileobj"),
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
        patch("app.services.document_upload_service.storage.upload_fileobj"),
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


async def test_reprocess_resets_status_and_requeues(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.upload_fileobj"),
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
        async with async_session_factory() as session:
            document = await session.get(Document, uuid.UUID(created["id"]))
            await DocumentUploadService(session).reprocess(document, "dev-user")

    mock_enqueue.assert_called_once_with(created["id"], bulk=False, task_id=ANY)
    mock_delete.assert_called_once_with(["old.png"])

    async with async_session_factory() as session:
        document = await session.get(Document, uuid.UUID(created["id"]))
        assert document.status == DocumentStatus.PENDING
        assert document.progress == 0
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
        await entities.replace_window(
            collection_id,
            report_id,
            "pages:1-2",
            [("Acme Corp", "organisation", 1), ("Alice", "personne", 1)],
            [("Alice", "Acme Corp", "works_at")],
        )
        await entities.replace_window(collection_id, memo_id, "pages:1-2", [("Acme Corp", "organisation", 1)], [])
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


async def _add_url_document(client, collection_id: str) -> str:
    with patch("app.services.document_upload_service.enqueue_process_document", return_value=str(uuid.uuid4())):
        response = await client.post(
            f"/api/collections/{collection_id}/documents/url",
            # The same URL twice is a duplicate to confirm (#300); these tests only need documents.
            json={"url": "https://example.com", "allow_duplicate": True},
        )
    return response.json()["id"]


async def test_documents_are_readable_but_not_writable_by_a_non_owner_of_a_public_collection(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    collection_id = await _create_collection(client)
    document_id = await _add_url_document(client, collection_id)
    await client.patch(f"/api/collections/{collection_id}/visibility", json={"visibility": "public"})

    try:
        app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")
        listed = await client.get(f"/api/collections/{collection_id}/documents")
        assert listed.status_code == 200
        assert [document["id"] for document in listed.json()] == [document_id]
        assert (await client.get(f"/api/collections/{collection_id}/documents/{document_id}")).status_code == 200
        assert (
            await client.post(f"/api/collections/{collection_id}/documents/url", json={"url": "https://example.com"})
        ).status_code == 404
        assert (await client.delete(f"/api/collections/{collection_id}/documents/{document_id}")).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_documents_of_a_private_collection_are_hidden_from_a_stranger(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    collection_id = await _create_collection(client)

    try:
        app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")
        assert (await client.get(f"/api/collections/{collection_id}/documents")).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_collection_reports_its_document_counts(client):
    collection_id = await _create_collection(client)
    indexed_id = await _add_url_document(client, collection_id)
    await _add_url_document(client, collection_id)
    async with async_session_factory() as session:
        document = await session.get(Document, uuid.UUID(indexed_id))
        document.status = DocumentStatus.INDEXED
        await session.commit()

    items = (await client.get("/api/collections")).json()["items"]
    listed = next(item for item in items if item["id"] == collection_id)
    detail = (await client.get(f"/api/collections/{collection_id}")).json()

    for body in (listed, detail):
        assert body["document_count"] == 2
        assert body["indexed_document_count"] == 1


async def test_a_file_of_any_size_is_taken_by_default(client):
    from app.services import document_upload_service

    assert document_upload_service._document_settings.DOCUMENT_MAX_UPLOAD_BYTES is None


async def test_a_file_over_the_upload_limit_is_refused_when_one_is_set(client, monkeypatch):
    from app.services import document_upload_service

    monkeypatch.setattr(document_upload_service._document_settings, "DOCUMENT_MAX_UPLOAD_BYTES", 2 * 1024 * 1024)
    collection_id = await _create_collection(client)

    with (
        patch("app.services.document_upload_service.storage.upload_fileobj") as mock_upload,
        patch("app.services.document_upload_service.enqueue_process_document") as mock_enqueue,
    ):
        response = await client.post(
            f"/api/collections/{collection_id}/documents/file",
            files={"file": ("big.pdf", b"x" * (2 * 1024 * 1024 + 1), "application/pdf")},
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
    assert "2 Mo" in response.json()["detail"]["message"]
    mock_upload.assert_not_called()
    mock_enqueue.assert_not_called()


# --- Relaunching the indexing of documents in error (#340) ---


@pytest.fixture
def relaunch():
    """What a relaunch touches outside the database replaced: the queue, the index, the object store and the
    tasks the document still has running."""
    enqueued = MagicMock(side_effect=lambda document_id, **options: f"celery-{document_id}")
    revoked = MagicMock()
    with (
        patch("app.services.document_upload_service.enqueue_process_document", enqueued),
        patch("app.services.document_upload_service.vector_store", MagicMock()),
        patch("app.services.document_upload_service.storage", MagicMock()),
        patch("app.services.document_upload_service.revoke_tasks", revoked),
    ):
        enqueued.revoked = revoked
        yield enqueued


async def _fail(*document_ids: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id.in_([uuid.UUID(document_id) for document_id in document_ids]))
            .values(status=DocumentStatus.ERROR, error="OCR failed")
        )
        await session.commit()


async def _status(document_id: str) -> DocumentStatus:
    async with async_session_factory() as session:
        return (await session.get(Document, uuid.UUID(document_id))).status


async def test_a_document_in_error_is_relaunched_from_scratch(client, relaunch):
    collection_id = await _create_collection(client)
    document_id = await _add_url_document(client, collection_id)
    await _fail(document_id)
    relaunch.reset_mock()

    response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/reprocess")

    assert response.status_code == 200
    assert response.json()["status"] == "pending" and response.json()["progress"] == 0
    relaunch.assert_called_once_with(document_id, bulk=False, task_id=ANY)
    async with async_session_factory() as session:
        task = await session.scalar(
            select(Task).where(
                Task.document_id == uuid.UUID(document_id), Task.celery_task_id == f"celery-{document_id}"
            )
        )
    assert task is not None and task.task_name == "app.tasks.process_document"


async def test_a_document_that_is_not_in_error_is_not_relaunched(client, relaunch):
    collection_id = await _create_collection(client)
    document_id = await _add_url_document(client, collection_id)
    relaunch.reset_mock()

    response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/reprocess")

    assert response.status_code == 409
    relaunch.assert_not_called()


async def test_relaunching_an_unknown_document_is_a_404(client, relaunch):
    collection_id = await _create_collection(client)

    response = await client.post(f"/api/collections/{collection_id}/documents/{uuid.uuid4()}/reprocess")

    assert response.status_code == 404


async def test_only_the_owner_relaunches_a_document(client, relaunch):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    collection_id = await _create_collection(client)
    document_id = await _add_url_document(client, collection_id)
    await _fail(document_id)
    await client.patch(f"/api/collections/{collection_id}/visibility", json={"visibility": "public"})
    relaunch.reset_mock()

    try:
        app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")
        one = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/reprocess")
        bulk = await client.post(f"/api/collections/{collection_id}/documents/reprocess-failed")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert one.status_code == 404 and bulk.status_code == 404
    relaunch.assert_not_called()
    assert await _status(document_id) == DocumentStatus.ERROR


async def test_a_document_that_still_has_tasks_running_has_them_stopped_before_it_is_relaunched(client, relaunch):
    collection_id = await _create_collection(client)
    document_id = await _add_url_document(client, collection_id)
    await _fail(document_id)
    async with async_session_factory() as session:
        task = (await session.execute(select(Task).where(Task.document_id == uuid.UUID(document_id)))).scalars().first()

    await client.post(f"/api/collections/{collection_id}/documents/{document_id}/reprocess")

    # The task the upload recorded is still PENDING: it is stopped before the document is queued again.
    relaunch.revoked.assert_called_once_with([task.celery_task_id])


async def test_every_document_in_error_of_a_collection_and_its_sub_collections_is_relaunched(client, relaunch):
    collection_id = await _create_collection(client)
    sub_id = (await client.post("/api/collections", json={"name": "Sous", "parent_id": collection_id})).json()["id"]
    failed = [await _add_url_document(client, collection_id) for _ in range(2)]
    failed.append(await _add_url_document(client, sub_id))
    fine = await _add_url_document(client, collection_id)
    await _fail(*failed)
    relaunch.reset_mock()

    response = await client.post(f"/api/collections/{collection_id}/documents/reprocess-failed")

    assert response.json() == {"reprocessed": 3}
    # One of many: processed after any other waiting.
    assert sorted(call.args[0] for call in relaunch.call_args_list) == sorted(failed)
    assert all(call.kwargs["bulk"] is True for call in relaunch.call_args_list)
    assert [await _status(document_id) for document_id in failed] == [DocumentStatus.PENDING] * 3
    assert await _status(fine) == DocumentStatus.PENDING


async def test_a_relaunch_in_bulk_can_leave_the_sub_collections_alone(client, relaunch):
    collection_id = await _create_collection(client)
    sub_id = (await client.post("/api/collections", json={"name": "Sous", "parent_id": collection_id})).json()["id"]
    here, below = await _add_url_document(client, collection_id), await _add_url_document(client, sub_id)
    await _fail(here, below)

    response = await client.post(f"/api/collections/{collection_id}/documents/reprocess-failed?recursive=false")

    assert response.json() == {"reprocessed": 1}
    assert await _status(below) == DocumentStatus.ERROR


async def test_a_cancelled_document_is_relaunched_like_one_in_error(client, relaunch):
    """Cancelling a task marks its document as in error ("Traitement annulé.") - it can be relaunched."""
    collection_id = await _create_collection(client)
    document_id = await _add_url_document(client, collection_id)
    async with async_session_factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id == uuid.UUID(document_id))
            .values(status=DocumentStatus.ERROR, error="Traitement annulé.")
        )
        await session.commit()

    response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/reprocess")

    assert response.status_code == 200
