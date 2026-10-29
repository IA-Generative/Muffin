import uuid
from datetime import UTC, datetime, time, timedelta
from unittest.mock import ANY, patch
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings, CollectionVisibility
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.document_refresh_schedule import DocumentRefreshSchedule, RefreshKind
from app.models.task import Task
from app.services.document_refresh_service import next_run
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
        patch(f"{UPLOAD}.enqueue_process_document", side_effect=lambda _id, **_: str(uuid.uuid4())) as enqueue,
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


EVERY_HOUR = {"kind": "interval", "interval_minutes": 60}


async def _schedule_due(document_id, minutes_ago=5, kind=RefreshKind.INTERVAL, **fields):
    async with async_session_factory() as session:
        session.add(
            DocumentRefreshSchedule(
                document_id=document_id,
                kind=kind,
                interval_minutes=fields.get("interval_minutes", 60 if kind == RefreshKind.INTERVAL else None),
                time_of_day=fields.get("time_of_day"),
                weekdays=fields.get("weekdays"),
                timezone="Europe/Paris",
                next_run_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            )
        )
        await session.commit()


async def _row(model, document_id):
    async with async_session_factory() as session:
        if model is Document:
            return await session.get(Document, document_id)
        return await session.scalar(select(model).where(model.document_id == document_id))


def _on_grid(moment: datetime) -> bool:
    return moment.minute in (0, 30) and moment.second == 0 and moment.microsecond == 0


# -- setting the schedule -----------------------------------------------------------------------


async def test_the_owner_sets_an_interval_and_the_first_run_is_on_the_scan_grid(client):
    collection_id, document_id = await _document()

    response = await client.put(_url(collection_id, document_id), json={"schedule": {**EVERY_HOUR}})

    assert response.status_code == 200
    body = response.json()
    assert body["schedule"]["kind"] == "interval" and body["schedule"]["interval_minutes"] == 60
    next_run = datetime.fromisoformat(body["next_run_at"])
    assert _on_grid(next_run)
    assert timedelta(minutes=60) <= next_run - datetime.now(UTC) <= timedelta(minutes=90)
    assert (await client.get(_url(collection_id, document_id))).json()["schedule"]["interval_minutes"] == 60


async def test_a_single_fetch_at_a_date_and_time(client):
    collection_id, document_id = await _document()
    run_at = (datetime.now(UTC) + timedelta(days=2)).replace(minute=30, second=0, microsecond=0)

    body = (
        await client.put(
            _url(collection_id, document_id), json={"schedule": {"kind": "once", "run_at": run_at.isoformat()}}
        )
    ).json()

    assert datetime.fromisoformat(body["next_run_at"]) == run_at
    assert datetime.fromisoformat(body["schedule"]["run_at"]) == run_at


async def test_every_day_at_a_time_of_the_owners_time_zone(client):
    collection_id, document_id = await _document()

    body = (
        await client.put(
            _url(collection_id, document_id),
            json={"schedule": {"kind": "daily", "time_of_day": "09:30", "timezone": "Europe/Paris"}},
        )
    ).json()

    local = datetime.fromisoformat(body["next_run_at"]).astimezone(ZoneInfo("Europe/Paris"))
    assert (local.hour, local.minute) == (9, 30)
    assert timedelta(0) < local - datetime.now(UTC) <= timedelta(days=1)


async def test_some_days_of_the_week_at_a_time(client):
    collection_id, document_id = await _document()

    body = (
        await client.put(
            _url(collection_id, document_id),
            json={"schedule": {"kind": "weekly", "time_of_day": "18:00", "weekdays": [4, 0, 4]}},
        )
    ).json()

    assert body["schedule"]["weekdays"] == [0, 4]
    local = datetime.fromisoformat(body["next_run_at"]).astimezone(ZoneInfo("Europe/Paris"))
    assert local.weekday() in (0, 4) and (local.hour, local.minute) == (18, 0)


async def test_stopping_the_refresh_removes_the_schedule(client):
    collection_id, document_id = await _document()
    await client.put(_url(collection_id, document_id), json={"schedule": EVERY_HOUR})

    response = await client.put(_url(collection_id, document_id), json={"schedule": None})

    assert response.json() == {"schedule": None, "next_run_at": None, "last_fetched_at": None}
    assert await _row(DocumentRefreshSchedule, document_id) is None


@pytest.mark.parametrize(
    "schedule",
    [
        {"kind": "interval", "interval_minutes": 45},
        {"kind": "interval", "interval_minutes": 0},
        {"kind": "interval", "interval_minutes": 7 * 24 * 60 + 30},
        {"kind": "interval"},
        {"kind": "daily", "time_of_day": "09:15"},
        {"kind": "daily"},
        {"kind": "weekly", "time_of_day": "09:00", "weekdays": []},
        {"kind": "weekly", "time_of_day": "09:00", "weekdays": [7]},
        {"kind": "once", "run_at": "2020-01-01T10:00:00+00:00"},
        {"kind": "once", "run_at": "2099-01-01T10:10:00+00:00"},
        {"kind": "once", "run_at": "2099-01-01T10:00:00"},
        {"kind": "daily", "time_of_day": "09:00", "timezone": "Mars/Olympus"},
    ],
)
async def test_only_times_on_the_scan_grid_are_accepted(client, schedule):
    collection_id, document_id = await _document()

    assert (await client.put(_url(collection_id, document_id), json={"schedule": schedule})).status_code == 422


async def test_a_file_cannot_be_refreshed(client):
    collection_id, document_id = await _document(type_=DocumentType.FILE)

    response = await client.put(_url(collection_id, document_id), json={"schedule": EVERY_HOUR})

    assert response.status_code == 409 and response.json()["detail"]["code"] == "not_url_document"


async def test_a_reader_sees_the_schedule_and_only_the_owner_changes_it(client):
    collection_id, document_id = await _document(owner="owner", visibility=CollectionVisibility.PUBLIC)
    app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")

    assert (await client.get(_url(collection_id, document_id))).status_code == 200
    assert (await client.put(_url(collection_id, document_id), json={"schedule": EVERY_HOUR})).status_code == 404
    assert await _row(DocumentRefreshSchedule, document_id) is None


async def test_the_schedule_is_set_when_the_url_is_added(client, pipeline):
    collection_id, _ = await _document()

    response = await client.post(
        f"/api/collections/{collection_id}/documents/url",
        json={"url": "https://example.com/rapport.pdf", "refresh_schedule": {"kind": "daily", "time_of_day": "07:00"}},
    )

    assert response.status_code == 201
    schedule = await _row(DocumentRefreshSchedule, uuid.UUID(response.json()["id"]))
    assert schedule.kind == RefreshKind.DAILY and schedule.time_of_day == time(7, 0)


async def test_a_url_added_without_a_schedule_is_never_refreshed(client, pipeline):
    collection_id, _ = await _document()

    response = await client.post(
        f"/api/collections/{collection_id}/documents/url", json={"url": "https://example.com/"}
    )

    assert await _row(DocumentRefreshSchedule, uuid.UUID(response.json()["id"])) is None


async def test_an_invalid_schedule_adds_nothing(client, pipeline):
    collection_id, _ = await _document()

    response = await client.post(
        f"/api/collections/{collection_id}/documents/url",
        json={"url": "https://example.com/", "refresh_schedule": {"kind": "daily", "time_of_day": "07:10"}},
    )

    assert response.status_code == 422
    pipeline[0].assert_not_called()


# -- the next run -------------------------------------------------------------------------------


def _stored(kind, next_run_at=None, **fields):
    return DocumentRefreshSchedule(kind=kind, timezone="Europe/Paris", next_run_at=next_run_at, **fields)


def test_an_interval_counts_from_the_previous_run_and_skips_missed_ones():
    planned = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
    schedule = _stored(RefreshKind.INTERVAL, planned, interval_minutes=120)

    # Claimed a few minutes late: no drift.
    assert next_run(schedule, planned + timedelta(minutes=3)) == planned + timedelta(hours=2)
    # The scan was down for five hours: the runs missed are not caught up one after the other.
    assert next_run(schedule, planned + timedelta(hours=5)) == planned + timedelta(hours=6)


def test_a_single_fetch_has_no_next_run():
    assert next_run(_stored(RefreshKind.ONCE, datetime.now(UTC)), datetime.now(UTC)) is None


def test_a_daily_time_stays_at_that_wall_clock_time_across_daylight_saving():
    schedule = _stored(RefreshKind.DAILY, time_of_day=time(9, 0))
    # Paris leaves summer time on 2026-10-25: 9:00 is 07:00 UTC before, 08:00 UTC after.
    assert next_run(schedule, datetime(2026, 10, 24, 8, 0, tzinfo=UTC)) == datetime(2026, 10, 25, 8, 0, tzinfo=UTC)
    assert next_run(schedule, datetime(2026, 10, 23, 6, 0, tzinfo=UTC)) == datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


def test_a_weekly_schedule_goes_to_the_next_day_chosen():
    # Mondays and Thursdays at 18:00, Paris (UTC+2 in October until the 25th).
    schedule = _stored(RefreshKind.WEEKLY, time_of_day=time(18, 0), weekdays=[0, 3])
    wednesday = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    thursday_evening = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)

    assert next_run(schedule, wednesday) == thursday_evening
    # Right after Thursday's run: next Monday (winter time by then, UTC+1).
    assert next_run(schedule, thursday_evening) == datetime(2026, 10, 26, 17, 0, tzinfo=UTC)


# -- the scan claims what is due, once ----------------------------------------------------------


async def test_the_scan_claims_due_documents_once_and_moves_their_next_run(client):
    _, due_id = await _document()
    _, later_id = await _document()
    await _schedule_due(due_id, minutes_ago=5)
    await _schedule_due(later_id, minutes_ago=-30)  # due in 30 minutes

    first = (await client.post("/api/internal/url-refresh/claim", headers=WORKER)).json()
    second = (await client.post("/api/internal/url-refresh/claim", headers=WORKER)).json()

    assert first["document_ids"] == [str(due_id)]
    assert second["document_ids"] == []  # a second scan (another replica) gets nothing
    schedule = await _row(DocumentRefreshSchedule, due_id)
    assert timedelta(minutes=50) < schedule.next_run_at - datetime.now(UTC) <= timedelta(minutes=55)


async def test_a_single_fetch_goes_away_once_claimed(client):
    _, document_id = await _document()
    await _schedule_due(document_id, kind=RefreshKind.ONCE)

    claimed = (await client.post("/api/internal/url-refresh/claim", headers=WORKER)).json()

    assert claimed["document_ids"] == [str(document_id)]
    assert await _row(DocumentRefreshSchedule, document_id) is None


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
    enqueue.assert_called_once_with(str(document_id), bulk=False, task_id=ANY)
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


async def test_a_url_serving_a_file_records_where_the_worker_stored_it(client):
    collection_id, document_id = await _document()
    key = f"documents/{collection_id}/{document_id}-rapport.pdf"

    response = await client.put(
        f"/api/internal/documents/{document_id}/content-hash",
        json={"content_hash": HASH_A, "storage_key": key},
        headers=WORKER,
    )

    assert response.status_code == 200
    assert (await _row(Document, document_id)).storage_key == key


async def test_a_stored_file_must_be_in_the_documents_collection(client):
    _, document_id = await _document()

    response = await client.put(
        f"/api/internal/documents/{document_id}/content-hash",
        json={"content_hash": HASH_A, "storage_key": f"documents/{uuid.uuid4()}/x.pdf"},
        headers=WORKER,
    )

    assert response.status_code == 422
    assert (await _row(Document, document_id)).storage_key is None


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


# -- fetching now ----------------------------------------------------------------------------------

REFRESH_NOW = "app.services.document_refresh_service.enqueue_refresh_url_document"


async def test_refresh_now_queues_a_fetch_recorded_as_the_users_task(client):
    collection_id, document_id = await _document()

    with patch(REFRESH_NOW, return_value="celery-refresh-1") as enqueue:
        response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/refresh")

    assert response.status_code == 202
    enqueue.assert_called_once_with(str(document_id), task_id=ANY)
    async with async_session_factory() as session:
        task = (await session.execute(select(Task).where(Task.celery_task_id == "celery-refresh-1"))).scalar_one()
    assert response.json() == {"task_id": str(task.id)}
    assert (task.task_name, task.owner_id, task.document_id) == (
        "app.tasks.refresh_url_document",
        "dev-user",
        document_id,
    )


async def test_refresh_now_leaves_the_schedule_alone(client):
    collection_id, document_id = await _document()
    await client.put(
        f"/api/collections/{collection_id}/documents/{document_id}/refresh-schedule",
        json={"schedule": {"kind": "interval", "interval_minutes": 60}},
    )
    before = (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/refresh-schedule")).json()

    with patch(REFRESH_NOW, return_value="celery-refresh-2"):
        await client.post(f"/api/collections/{collection_id}/documents/{document_id}/refresh")

    after = (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/refresh-schedule")).json()
    assert after == before


async def test_refresh_now_of_a_file_document_is_refused(client):
    collection_id, document_id = await _document(type_=DocumentType.FILE)

    with patch(REFRESH_NOW) as enqueue:
        response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/refresh")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_url_document"
    enqueue.assert_not_called()


async def test_refresh_now_of_a_document_being_processed_is_refused(client):
    collection_id, document_id = await _document(status=DocumentStatus.INDEXING)

    with patch(REFRESH_NOW) as enqueue:
        response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/refresh")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_processing"
    enqueue.assert_not_called()


async def test_refresh_now_is_for_the_owner_only(client):
    collection_id, document_id = await _document(owner="someone-else", visibility=CollectionVisibility.PUBLIC)

    with patch(REFRESH_NOW) as enqueue:
        response = await client.post(f"/api/collections/{collection_id}/documents/{document_id}/refresh")

    assert response.status_code == 404
    enqueue.assert_not_called()
