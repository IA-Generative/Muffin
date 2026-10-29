import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.task import Task
from app.models.task_log_entry import TaskLogEntry


@pytest.fixture
async def client():
    # See tests/routers/test_collections.py for why this isn't the sync TestClient.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(TaskLogEntry))
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


def _as_user(user_id: str, email: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False)

    return override


async def _set_status(celery_task_id: str, status: str) -> None:
    """What a worker reports as it runs the task (see the internal status endpoint)."""
    async with async_session_factory() as session:
        await session.execute(update(Task).where(Task.celery_task_id == celery_task_id).values(status=status))
        await session.commit()


async def _create_document(client) -> tuple[str, str]:
    collection_id = (await client.post("/api/collections")).json()["id"]
    with (
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-abc"),
    ):
        document = (
            await client.post(f"/api/collections/{collection_id}/documents/url", json={"url": "https://example.com"})
        ).json()
    return collection_id, document["id"]


async def test_list_tasks_reports_status_and_linked_document(client):
    collection_id, document_id = await _create_document(client)
    await _set_status("celery-abc", "STARTED")

    response = await client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    task = body["items"][0]
    assert task["task_name"] == "app.tasks.process_document"
    assert task["status"] == "STARTED"
    assert task["document_id"] == document_id
    assert task["document_name"] == "https://example.com"
    assert task["collection_id"] == collection_id
    assert task["parent_id"] is None


async def test_list_tasks_pagination_counts_runs_not_raw_rows(client):
    """A run's child tasks (parent_id set) must never count against the page
    total or push a later run onto another page - only root runs do."""
    from app.repositories.task_repository import TaskRepository

    collection_id, document_id = await _create_document(client)
    async with async_session_factory() as session:
        repo = TaskRepository(session)
        root = await repo.get_by_celery_id("celery-abc")
        for i in range(5):
            await repo.create(
                f"celery-child-{i}",
                "app.tasks.chunk_document",
                "dev-user",
                document_id=uuid.UUID(document_id),
                collection_id=uuid.UUID(collection_id),
                parent_id=root.id,
            )
        await session.commit()

    response = await client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    # 1 run total (the root), but its 5 children still come back alongside it.
    assert body["total"] == 1
    assert len(body["items"]) == 6


async def test_list_tasks_is_scoped_to_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    await _create_document(client)
    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")

    response = await client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


async def _add_children(client, document_id, collection_id, count=2, parent_celery_id="celery-abc"):
    """Children of the first task, as the pipeline records them (chunk_document, then its windows)."""
    from app.repositories.task_repository import TaskRepository

    async with async_session_factory() as session:
        repo = TaskRepository(session)
        root = await repo.get_by_celery_id(parent_celery_id)
        for i in range(count):
            await repo.create(
                f"celery-child-{i}",
                "app.tasks.chunk_document",
                "dev-user",
                document_id=uuid.UUID(document_id),
                collection_id=uuid.UUID(collection_id),
                parent_id=root.id,
            )
        await session.commit()


async def test_revoke_task(client):
    _, document_id = await _create_document(client)
    await _set_status("celery-abc", "STARTED")

    with patch("app.services.task_service.revoke_tasks") as mock_revoke:
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]
        response = await client.post(f"/api/tasks/{task_id}/revoke")

    assert response.status_code == 200
    # Told as it is, not as the worker will report it a few seconds later.
    assert response.json()["status"] == "REVOKED"
    mock_revoke.assert_called_once_with(["celery-abc"])


async def test_revoking_a_task_revokes_the_tasks_it_started_that_are_still_active(client):
    collection_id, document_id = await _create_document(client)
    await _add_children(client, document_id, collection_id, count=3)
    # The root and one child are still going; the other children are over.
    await _set_status("celery-abc", "STARTED")
    await _set_status("celery-child-1", "STARTED")
    await _set_status("celery-child-0", "SUCCESS")
    await _set_status("celery-child-2", "FAILURE")

    with patch("app.services.task_service.revoke_tasks") as mock_revoke:
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]
        await client.post(f"/api/tasks/{task_id}/revoke")

    assert sorted(mock_revoke.call_args.args[0]) == ["celery-abc", "celery-child-1"]


async def test_revoking_a_task_that_is_over_leaves_it_as_it_ended(client):
    _, document_id = await _create_document(client)
    await _set_status("celery-abc", "SUCCESS")

    with patch("app.services.task_service.revoke_tasks") as mock_revoke:
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]
        response = await client.post(f"/api/tasks/{task_id}/revoke")

    assert response.json()["status"] == "SUCCESS"
    mock_revoke.assert_called_once_with([])


async def _document_state(document_id: str) -> tuple[str, str | None]:
    from app.models.document import Document

    async with async_session_factory() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        return document.status, document.error


async def test_revoking_the_processing_of_a_document_marks_it_as_cancelled(client):
    _, document_id = await _create_document(client)  # a new document is pending
    await _set_status("celery-abc", "STARTED")

    with patch("app.services.task_service.revoke_tasks"):
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]
        await client.post(f"/api/tasks/{task_id}/revoke")

    assert await _document_state(document_id) == ("error", "Traitement annulé.")


async def test_revoking_a_task_of_a_document_already_indexed_leaves_the_document_alone(client):
    from app.models.document import Document, DocumentStatus

    _, document_id = await _create_document(client)
    async with async_session_factory() as session:
        (await session.get(Document, uuid.UUID(document_id))).status = DocumentStatus.INDEXED
        await session.commit()
    await _set_status("celery-abc", "STARTED")

    with patch("app.services.task_service.revoke_tasks"):
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]
        await client.post(f"/api/tasks/{task_id}/revoke")

    assert await _document_state(document_id) == ("indexed", None)


async def test_revoke_unknown_task_returns_404(client):
    response = await client.post(f"/api/tasks/{uuid.uuid4()}/revoke")
    assert response.status_code == 404


async def test_revoke_someone_elses_task_returns_404(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    await _create_document(client)
    task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.post(f"/api/tasks/{task_id}/revoke")
    assert response.status_code == 404


async def _log(celery_task_id: str, document_id: str | None, *lines: tuple[str, str]) -> list[int]:
    """Records (level, message) lines as a worker would, returns their ids."""
    async with async_session_factory() as session:
        entries = [
            TaskLogEntry(
                celery_task_id=celery_task_id,
                task_name=f"app.tasks.{celery_task_id}",
                document_id=uuid.UUID(document_id) if document_id else None,
                ts=datetime.now(UTC),
                level=level,
                message=message,
            )
            for level, message in lines
        ]
        session.add_all(entries)
        await session.commit()
        return [entry.id for entry in entries]


async def _task_id(client) -> str:
    return (await client.get("/api/tasks")).json()["items"][0]["id"]


async def test_get_task_logs_returns_its_lines_in_order(client):
    _, document_id = await _create_document(client)
    task_id = await _task_id(client)
    await _log("celery-abc", document_id, ("INFO", "first"), ("ERROR", "second"))
    await _log("celery-other", document_id, ("INFO", "another task's"))

    response = await client.get(f"/api/tasks/{task_id}/logs")

    assert response.status_code == 200
    body = response.json()
    assert [(entry["level"], entry["message"]) for entry in body["entries"]] == [("INFO", "first"), ("ERROR", "second")]
    assert body["has_more"] is False


async def test_get_task_logs_after_a_line_returns_only_the_ones_logged_since(client):
    _, document_id = await _create_document(client)
    task_id = await _task_id(client)
    first, _ = await _log("celery-abc", document_id, ("INFO", "first"), ("INFO", "second"))

    response = await client.get(f"/api/tasks/{task_id}/logs", params={"after": first})

    assert [entry["message"] for entry in response.json()["entries"]] == ["second"]


async def test_get_task_logs_from_a_level_up(client):
    _, document_id = await _create_document(client)
    task_id = await _task_id(client)
    await _log("celery-abc", document_id, ("DEBUG", "debug"), ("INFO", "info"), ("WARNING", "warning"))

    response = await client.get(f"/api/tasks/{task_id}/logs", params={"level": "warning"})

    assert [entry["message"] for entry in response.json()["entries"]] == ["warning"]


async def test_get_task_logs_tells_when_there_are_more_than_one_page(client, monkeypatch):
    monkeypatch.setattr("app.services.task_service.LOG_PAGE_SIZE", 2)
    _, document_id = await _create_document(client)
    task_id = await _task_id(client)
    await _log("celery-abc", document_id, ("INFO", "1"), ("INFO", "2"), ("INFO", "3"))

    body = (await client.get(f"/api/tasks/{task_id}/logs")).json()

    assert [entry["message"] for entry in body["entries"]] == ["1", "2"]
    assert body["has_more"] is True


async def test_get_task_logs_not_found(client):
    response = await client.get(f"/api/tasks/{uuid.uuid4()}/logs")
    assert response.status_code == 404


async def test_get_someone_elses_task_logs_returns_404(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    await _create_document(client)
    task_id = await _task_id(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.get(f"/api/tasks/{task_id}/logs")
    assert response.status_code == 404


async def test_get_document_logs_puts_every_task_of_its_pipeline_on_one_timeline(client):
    collection_id, document_id = await _create_document(client)
    await _log("process_document", document_id, ("INFO", "extracted"))
    await _log("chunk_document", document_id, ("INFO", "chunked"))
    await _log("chunk_document", None, ("INFO", "of no document"))

    response = await client.get(f"/api/collections/{collection_id}/documents/{document_id}/logs")

    assert response.status_code == 200
    assert [(entry["task_name"], entry["message"]) for entry in response.json()["entries"]] == [
        ("app.tasks.process_document", "extracted"),
        ("app.tasks.chunk_document", "chunked"),
    ]


async def test_get_document_logs_of_someone_elses_collection_returns_404(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    collection_id, document_id = await _create_document(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.get(f"/api/collections/{collection_id}/documents/{document_id}/logs")
    assert response.status_code == 404


async def test_get_document_logs_of_a_document_of_another_collection_returns_404(client):
    _, document_id = await _create_document(client)
    other_collection_id = (await client.post("/api/collections")).json()["id"]

    response = await client.get(f"/api/collections/{other_collection_id}/documents/{document_id}/logs")
    assert response.status_code == 404
