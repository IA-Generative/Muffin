import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.task import Task


@pytest.fixture
async def client():
    # See tests/routers/test_collections.py for why this isn't the sync TestClient.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


def _as_user(user_id: str, email: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False)

    return override


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

    with patch("app.services.task_service.get_task_status", return_value="STARTED"):
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
    assert task["log_preview"] == ""
    assert task["has_more_logs"] is False


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

    with patch("app.services.task_service.get_task_status", return_value="SUCCESS"):
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

    with patch("app.services.task_service.get_task_status", return_value="PENDING"):
        response = await client.get("/api/tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_revoke_task(client):
    _, document_id = await _create_document(client)

    with (
        patch("app.services.task_service.get_task_status", return_value="REVOKED"),
        patch("app.services.task_service.revoke_task") as mock_revoke,
    ):
        list_response = await client.get("/api/tasks")
        task_id = list_response.json()["items"][0]["id"]
        response = await client.post(f"/api/tasks/{task_id}/revoke")

    assert response.status_code == 200
    assert response.json()["status"] == "REVOKED"
    mock_revoke.assert_called_once_with("celery-abc")


async def test_revoke_unknown_task_returns_404(client):
    response = await client.post(f"/api/tasks/{uuid.uuid4()}/revoke")
    assert response.status_code == 404


async def test_revoke_someone_elses_task_returns_404(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    await _create_document(client)

    with patch("app.services.task_service.get_task_status", return_value="PENDING"):
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.post(f"/api/tasks/{task_id}/revoke")
    assert response.status_code == 404


async def test_get_task_logs_returns_full_content(client):
    from app.repositories.task_repository import TaskRepository

    _, document_id = await _create_document(client)

    with patch("app.services.task_service.get_task_status", return_value="STARTED"):
        task_id = (await client.get("/api/tasks")).json()["items"][0]["id"]

    async with async_session_factory() as session:
        task = await TaskRepository(session).get(uuid.UUID(task_id), "dev-user")
        task.logs = "full raw log output"
        await session.commit()

    response = await client.get(f"/api/tasks/{task_id}/logs")

    assert response.status_code == 200
    assert response.json() == {"id": task_id, "logs": "full raw log output"}


async def test_get_task_logs_not_found(client):
    response = await client.get(f"/api/tasks/{uuid.uuid4()}/logs")
    assert response.status_code == 404
