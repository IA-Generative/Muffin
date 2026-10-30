import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.task import Task
from app.models.task_log_entry import TaskLogEntry

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(TaskLogEntry))
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


def _line(celery_task_id: str, message: str, **fields) -> dict:
    return {
        "celery_task_id": celery_task_id,
        "task_name": "app.tasks.process_document",
        "ts": "2026-10-28T09:00:00+00:00",
        "level": "INFO",
        "message": message,
        **fields,
    }


async def _lines() -> list[TaskLogEntry]:
    async with async_session_factory() as session:
        return list((await session.execute(select(TaskLogEntry).order_by(TaskLogEntry.id))).scalars())


async def test_add_task_logs_records_each_line_in_order(client):
    document_id = uuid.uuid4()
    response = await client.post(
        "/api/internal/task-logs",
        headers=_headers(),
        json={
            "entries": [
                _line("celery-3", "first", document_id=str(document_id), extra={"function": "process_document"}),
                _line("celery-3", "second"),
                # A task the beat sent has no Task row: its lines are recorded all the same.
                _line("beat-scan", "scan", task_name="app.tasks.scan_url_refresh"),
            ]
        },
    )

    assert response.status_code == 204
    lines = await _lines()
    assert [line.message for line in lines] == ["first", "second", "scan"]
    assert lines[0].document_id == document_id
    assert lines[0].extra == {"function": "process_document"}
    assert lines[2].celery_task_id == "beat-scan"


async def test_add_task_logs_requires_the_worker_key(client):
    response = await client.post("/api/internal/task-logs", json={"entries": [_line("celery-3", "first")]})
    assert response.status_code == 401


async def test_purge_task_logs_deletes_only_the_lines_past_their_retention(client):
    old = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    await client.post(
        "/api/internal/task-logs",
        headers=_headers(),
        json={
            "entries": [_line("celery-4", "old", ts=old), _line("celery-4", "recent", ts=datetime.now(UTC).isoformat())]
        },
    )

    response = await client.delete("/api/internal/task-logs", headers=_headers())

    assert response.json() == {"deleted": 1}
    assert [line.message for line in await _lines()] == ["recent"]


async def test_update_task_logs_records_the_whole_output_as_one_line(client):
    """What a worker not yet upgraded sends, at the end of its task."""
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

    lines = await _lines()
    assert [(line.celery_task_id, line.message, line.document_id) for line in lines] == [
        ("celery-2", "line 1\nline 2", document_id)
    ]


async def test_update_task_logs_not_found(client):
    response = await client.patch("/api/internal/tasks/unknown/logs", headers=_headers(), json={"logs": "irrelevant"})
    assert response.status_code == 404


async def _task(celery_task_id: str) -> Task:
    async with async_session_factory() as session:
        return (await session.execute(select(Task).where(Task.celery_task_id == celery_task_id))).scalar_one()


async def _record_task(celery_task_id: str = "celery-status") -> None:
    document_id = await _create_document()
    async with async_session_factory() as session:
        session.add(
            Task(
                celery_task_id=celery_task_id,
                task_name="app.tasks.process_document",
                owner_id="dev-user",
                document_id=document_id,
            )
        )
        await session.commit()


async def test_update_task_status_records_the_start_and_the_end(client):
    await _record_task()

    started = await client.patch(
        "/api/internal/tasks/celery-status/status", headers=_headers(), json={"status": "STARTED"}
    )
    assert started.status_code == 204
    task = await _task("celery-status")
    assert task.status == "STARTED"
    assert task.started_at is not None
    assert task.finished_at is None

    finished = await client.patch(
        "/api/internal/tasks/celery-status/status",
        headers=_headers(),
        json={"status": "FAILURE", "error": "it went wrong"},
    )
    assert finished.status_code == 204
    task = await _task("celery-status")
    assert task.status == "FAILURE"
    assert task.finished_at is not None
    assert task.error == "it went wrong"


async def test_update_task_status_does_not_overwrite_a_revocation(client):
    await _record_task()
    async with async_session_factory() as session:
        await session.execute(update(Task).where(Task.celery_task_id == "celery-status").values(status="REVOKED"))
        await session.commit()

    response = await client.patch(
        "/api/internal/tasks/celery-status/status", headers=_headers(), json={"status": "SUCCESS"}
    )

    assert response.status_code == 204
    assert (await _task("celery-status")).status == "REVOKED"


async def test_update_task_status_for_a_task_with_no_row_is_a_no_op(client):
    response = await client.patch(
        "/api/internal/tasks/beat-scan/status", headers=_headers(), json={"status": "STARTED"}
    )
    assert response.status_code == 204


async def test_reap_stuck_tasks_marks_only_the_ones_started_before_the_timeout(client):
    await _record_task("celery-stuck")
    await _record_task("celery-running")
    old = datetime.now(UTC) - timedelta(hours=48)
    async with async_session_factory() as session:
        await session.execute(
            update(Task).where(Task.celery_task_id == "celery-stuck").values(status="STARTED", started_at=old)
        )
        await session.execute(
            update(Task)
            .where(Task.celery_task_id == "celery-running")
            .values(status="STARTED", started_at=datetime.now(UTC))
        )
        await session.commit()

    response = await client.post("/api/internal/tasks/reap", headers=_headers())

    assert response.json() == {"reaped": 1}
    assert (await _task("celery-stuck")).status == "FAILURE"
    assert (await _task("celery-running")).status == "STARTED"


async def test_update_task_status_refreshes_the_start_on_a_retry(client):
    await _record_task()
    old = datetime.now(UTC) - timedelta(hours=48)
    async with async_session_factory() as session:
        await session.execute(
            update(Task).where(Task.celery_task_id == "celery-status").values(status="STARTED", started_at=old)
        )
        await session.commit()

    response = await client.patch(
        "/api/internal/tasks/celery-status/status", headers=_headers(), json={"status": "STARTED"}
    )

    assert response.status_code == 204
    assert (await _task("celery-status")).started_at > old


async def test_update_task_status_clears_the_previous_attempts_end_and_error(client):
    await _record_task()
    async with async_session_factory() as session:
        await session.execute(
            update(Task)
            .where(Task.celery_task_id == "celery-status")
            .values(status="FAILURE", finished_at=datetime.now(UTC), error="previous attempt")
        )
        await session.commit()

    response = await client.patch(
        "/api/internal/tasks/celery-status/status", headers=_headers(), json={"status": "STARTED"}
    )

    assert response.status_code == 204
    task = await _task("celery-status")
    assert task.status == "STARTED"
    assert task.finished_at is None
    assert task.error is None


async def test_reap_stuck_tasks_leaves_unbounded_tasks_alone(client):
    await _record_task("celery-evaluation")
    old = datetime.now(UTC) - timedelta(hours=48)
    async with async_session_factory() as session:
        await session.execute(
            update(Task)
            .where(Task.celery_task_id == "celery-evaluation")
            .values(status="STARTED", started_at=old, task_name="app.tasks.run_evaluation")
        )
        await session.commit()

    response = await client.post("/api/internal/tasks/reap", headers=_headers())

    assert response.json() == {"reaped": 0}
    assert (await _task("celery-evaluation")).status == "STARTED"
