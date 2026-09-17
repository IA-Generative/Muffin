import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.task import Task

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _create_document() -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="report.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return document.id


async def test_create_task_resolves_owner_from_documents_collection(client):
    document_id = await _create_document()

    response = await client.post(
        "/api/internal/tasks",
        headers=_headers(),
        json={"celery_task_id": "celery-1", "task_name": "app.tasks.process_document", "document_id": str(document_id)},
    )

    assert response.status_code == 201
    async with async_session_factory() as session:
        from sqlalchemy import select

        task = (await session.execute(select(Task).where(Task.celery_task_id == "celery-1"))).scalar_one()
    assert task.owner_id == "dev-user"
    assert task.document_id == document_id
    assert task.parent_id is None


async def test_create_task_links_to_parent_by_celery_id(client):
    document_id = await _create_document()
    await client.post(
        "/api/internal/tasks",
        headers=_headers(),
        json={"celery_task_id": "parent-1", "task_name": "app.tasks.process_document", "document_id": str(document_id)},
    )

    response = await client.post(
        "/api/internal/tasks",
        headers=_headers(),
        json={
            "celery_task_id": "child-1",
            "task_name": "app.tasks.chunk_document",
            "document_id": str(document_id),
            "parent_celery_task_id": "parent-1",
        },
    )
    assert response.status_code == 201

    async with async_session_factory() as session:
        from sqlalchemy import select

        parent = (await session.execute(select(Task).where(Task.celery_task_id == "parent-1"))).scalar_one()
        child = (await session.execute(select(Task).where(Task.celery_task_id == "child-1"))).scalar_one()
    assert child.parent_id == parent.id


async def test_create_task_document_not_found(client):
    response = await client.post(
        "/api/internal/tasks",
        headers=_headers(),
        json={
            "celery_task_id": "celery-x",
            "task_name": "app.tasks.process_document",
            "document_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404


async def test_update_task_logs(client):
    document_id = await _create_document()
    await client.post(
        "/api/internal/tasks",
        headers=_headers(),
        json={"celery_task_id": "celery-2", "task_name": "app.tasks.process_document", "document_id": str(document_id)},
    )

    response = await client.patch(
        "/api/internal/tasks/celery-2/logs", headers=_headers(), json={"logs": "line 1\nline 2"}
    )
    assert response.status_code == 200

    async with async_session_factory() as session:
        from sqlalchemy import select

        task = (await session.execute(select(Task).where(Task.celery_task_id == "celery-2"))).scalar_one()
    assert task.logs == "line 1\nline 2"


async def test_update_task_logs_not_found(client):
    response = await client.patch("/api/internal/tasks/unknown/logs", headers=_headers(), json={"logs": "irrelevant"})
    assert response.status_code == 404
