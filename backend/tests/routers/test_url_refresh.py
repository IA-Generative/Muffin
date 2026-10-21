import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings, CollectionVisibility
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.document_refresh_schedule import DocumentRefreshSchedule
from app.models.task import Task
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"
WORKER = {"X-API-Key": API_KEY}
UPLOAD = "app.services.document_upload_service"
HASH_A = "a" * 64
HASH_B = "b" * 64


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


@pytest.fixture
def pipeline():
    """The processing queue, the vector store and the object store, faked."""
    with (
        patch(f"{UPLOAD}.enqueue_process_document", side_effect=lambda _id: str(uuid.uuid4())) as enqueue,
        patch(f"{UPLOAD}.vector_store.delete_document_embeddings") as embeddings,
        patch(f"{UPLOAD}.storage.delete_objects"),
    ):
        yield enqueue, embeddings


async def _document(
    *,
    owner="dev-user",
    type_=DocumentType.URL,
    status=DocumentStatus.INDEXED,
    content_hash=None,
    added_by=None,
    visibility=CollectionVisibility.PRIVATE,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner, name="Veille", description="", visibility=visibility)
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(
            collection_id=collection.id,
            name="https://example.com/page" if type_ == DocumentType.URL else "rapport.pdf",
            type=type_,
            status=status,
            summary="Résumé.",
            content_hash=content_hash,
            added_by_user_id=added_by,
        )
        session.add(document)
        await session.commit()
        return collection.id, document.id


def _url(collection_id, document_id):
    return f"/api/collections/{collection_id}/documents/{document_id}/refresh-schedule"


async def _schedule_due(document_id, minutes_ago=5, interval=60):
    async with async_session_factory() as session:
        session.add(
            DocumentRefreshSchedule(
                document_id=document_id,
                interval_minutes=interval,
                next_run_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            )
        )
        await session.commit()


async def _row(model, document_id):
    async with async_session_factory() as session:
        if model is Document:
            return await session.get(Document, document_id)
        return await session.scalar(select(model).where(model.document_id == document_id))


# -- setting the frequency ----------------------------------------------------------------------


async def test_the_owner_sets_how_often_a_url_is_fetched_again(client):
    collection_id, document_id = await _document()

    response = await client.put(_url(collection_id, document_id), json={"interval_minutes": 360})

    assert response.status_code == 200
    body = response.json()
    assert body["interval_minutes"] == 360
    next_run = datetime.fromisoformat(body["next_run_at"])
    assert timedelta(minutes=355) < next_run - datetime.now(UTC) <= timedelta(minutes=360)
    assert (await client.get(_url(collection_id, document_id))).json()["interval_minutes"] == 360


async def test_stopping_the_refresh_removes_the_schedule(client):
    collection_id, document_id = await _document()
    await client.put(_url(collection_id, document_id), json={"interval_minutes": 60})

    response = await client.put(_url(collection_id, document_id), json={"interval_minutes": None})

    assert response.json() == {"interval_minutes": None, "next_run_at": None, "last_fetched_at": None}
    assert await _row(DocumentRefreshSchedule, document_id) is None


@pytest.mark.parametrize("interval", [15, 45, 0, -30])
async def test_only_multiples_of_the_scan_are_offered(client, interval):
    collection_id, document_id = await _document()

    assert (await client.put(_url(collection_id, document_id), json={"interval_minutes": interval})).status_code == 422


async def test_a_file_cannot_be_refreshed(client):
    collection_id, document_id = await _document(type_=DocumentType.FILE)

    response = await client.put(_url(collection_id, document_id), json={"interval_minutes": 60})

    assert response.status_code == 409 and response.json()["detail"]["code"] == "not_url_document"


async def test_a_reader_sees_the_schedule_and_only_the_owner_changes_it(client):
    collection_id, document_id = await _document(owner="owner", visibility=CollectionVisibility.PUBLIC)
    app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")

    assert (await client.get(_url(collection_id, document_id))).status_code == 200
    assert (await client.put(_url(collection_id, document_id), json={"interval_minutes": 60})).status_code == 404
    assert await _row(DocumentRefreshSchedule, document_id) is None


# -- the scan claims what is due, once ----------------------------------------------------------


async def test_the_scan_claims_due_documents_once_and_moves_their_next_run(client):
    _, due_id = await _document()
    _, later_id = await _document()
    await _schedule_due(due_id, minutes_ago=5, interval=60)
    await _schedule_due(later_id, minutes_ago=-30)  # due in 30 minutes

    first = (await client.post("/api/internal/url-refresh/claim", headers=WORKER)).json()
    second = (await client.post("/api/internal/url-refresh/claim", headers=WORKER)).json()

    assert first["document_ids"] == [str(due_id)]
    assert second["document_ids"] == []  # a second scan (another replica) gets nothing
    schedule = await _row(DocumentRefreshSchedule, due_id)
    assert timedelta(minutes=55) < schedule.next_run_at - datetime.now(UTC) <= timedelta(minutes=60)


@pytest.mark.parametrize("status", [DocumentStatus.PENDING, DocumentStatus.INDEXING])
async def test_a_document_being_processed_is_left_for_a_later_scan(client, status):
    _, document_id = await _document(status=status)
    await _schedule_due(document_id)

    claimed = (await client.post("/api/internal/url-refresh/claim", headers=WORKER)).json()

    assert claimed["document_ids"] == []
    # Not claimed, so not pushed back a whole interval: the next scan picks it up.
    assert (await _row(DocumentRefreshSchedule, document_id)).next_run_at < datetime.now(UTC)


async def test_the_scan_needs_the_workers_key(client):
    assert (await client.post("/api/internal/url-refresh/claim")).status_code == 401


# -- what a fetched page leads to ---------------------------------------------------------------


async def _report(client, document_id, content_hash):
    return await client.post(
        f"/api/internal/documents/{document_id}/url-refresh", json={"content_hash": content_hash}, headers=WORKER
    )


async def test_an_unchanged_page_only_updates_the_date_of_the_check(client, pipeline):
    enqueue, _ = pipeline
    _, document_id = await _document(content_hash=HASH_A)

    response = await _report(client, document_id, HASH_A)

    assert response.json() == {"changed": False}
    enqueue.assert_not_called()
    document = await _row(Document, document_id)
    assert document.status == DocumentStatus.INDEXED and document.summary == "Résumé."
    assert document.last_fetched_at is not None


async def test_a_changed_page_reprocesses_the_document_from_scratch(client, pipeline):
    enqueue, embeddings = pipeline
    collection_id, document_id = await _document(content_hash=HASH_A, added_by="adder")

    response = await _report(client, document_id, HASH_B)

    assert response.json() == {"changed": True}
    enqueue.assert_called_once_with(str(document_id))
    embeddings.assert_called_once()  # the old vectors go before the new ones come
    document = await _row(Document, document_id)
    # Back to pending; its summary, like everything the pipeline derives, is replaced by the new run.
    assert document.status == DocumentStatus.PENDING
    # The new hash is recorded by the processing itself, from what it really indexes.
    assert document.content_hash == HASH_A
    async with async_session_factory() as session:
        task = await session.scalar(select(Task).where(Task.document_id == document_id))
    # Recorded for whoever added the document: their task list, their consumption.
    assert (task.owner_id, task.collection_id) == ("adder", collection_id)


async def test_a_url_indexed_before_hashes_existed_is_reprocessed_at_its_first_refresh(client, pipeline):
    enqueue, _ = pipeline
    _, document_id = await _document(content_hash=None)

    assert (await _report(client, document_id, HASH_A)).json() == {"changed": True}
    enqueue.assert_called_once()


async def test_a_document_already_being_processed_is_not_reprocessed_twice(client, pipeline):
    enqueue, _ = pipeline
    _, document_id = await _document(content_hash=HASH_A, status=DocumentStatus.INDEXING)

    assert (await _report(client, document_id, HASH_B)).json() == {"changed": False}
    enqueue.assert_not_called()


async def test_indexing_records_the_hash_of_the_page(client):
    _, document_id = await _document()

    response = await client.put(
        f"/api/internal/documents/{document_id}/content-hash", json={"content_hash": HASH_B}, headers=WORKER
    )

    assert response.status_code == 200
    document = await _row(Document, document_id)
    assert document.content_hash == HASH_B and document.last_fetched_at is not None
    bad = await client.put(
        f"/api/internal/documents/{document_id}/content-hash", json={"content_hash": "not-a-hash"}, headers=WORKER
    )
    assert bad.status_code == 422
