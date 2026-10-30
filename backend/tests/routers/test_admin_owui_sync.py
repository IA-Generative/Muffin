import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import tasks
from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentType
from app.models.index_rebuild import IndexRebuild, IndexRebuildStatus
from app.models.owui_sync_run import OwuiSyncRun


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)


def _as(is_admin: bool) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id="u", email="u@example.test", roles=[], is_admin=is_admin
    )


async def test_an_administrator_starts_a_synchronisation(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        tasks._celery_app,
        "send_task",
        lambda name, queue: sent.update(name=name, queue=queue) or type("R", (), {"id": "t1"})(),
    )
    _as(True)

    response = await client.post("/api/admin/owui-sync")

    assert response.status_code == 202
    assert response.json() == {"task_id": "t1"}
    assert sent == {"name": "app.tasks.sync_owui", "queue": "owui_sync"}


async def test_anyone_else_cannot(client, monkeypatch):
    monkeypatch.setattr(tasks, "enqueue_sync_owui", lambda: pytest.fail("must not be started"))
    _as(False)

    assert (await client.post("/api/admin/owui-sync")).status_code == 403


# -- the account of the synchronisations, for the administrators' page (#466) -----------------------------


API_KEY = "test-worker-key"
HEADERS = {"X-API-Key": API_KEY}
ACCOUNT = {
    "run": "r",
    "groups": {"seen": 1, "errors": 0, "dropped": 0},
    "knowledge_bases": {"seen": 2, "errors": 0, "unlisted": 0, "inconsistent": 0, "dropped": 0},
    "files": {"seen": 5, "errors": 0, "dropped": 0},
}


@pytest.fixture(autouse=True)
async def clean(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
    yield
    async with async_session_factory() as session:
        await session.execute(delete(OwuiSyncRun))
        await session.execute(delete(Collection))
        await session.commit()


async def _report(client, run_id, status, **body):
    return await client.put(f"/api/internal/owui-sync/runs/{run_id}", headers=HEADERS, json={"status": status, **body})


async def test_the_worker_key_is_needed_to_report_a_run(client):
    response = await client.put(f"/api/internal/owui-sync/runs/{uuid.uuid4()}", json={"status": "running"})

    assert response.status_code == 401


async def test_there_is_no_account_before_the_first_synchronisation(client):
    _as(True)

    response = await client.get("/api/admin/owui-sync")

    assert response.json() == {"latest": None, "running": False}


async def test_a_run_is_seen_running_then_done_with_its_account(client):
    _as(True)
    run_id = uuid.uuid4()
    started = datetime.now(UTC) - timedelta(minutes=2)

    await _report(client, run_id, "running", started_at=started.isoformat())
    during = (await client.get("/api/admin/owui-sync")).json()
    await _report(client, run_id, "done", account=ACCOUNT)
    after = (await client.get("/api/admin/owui-sync")).json()

    assert (during["running"], during["latest"]["status"], during["latest"]["account"]) == (True, "running", None)
    assert (after["running"], after["latest"]["status"], after["latest"]["account"]) == (False, "done", ACCOUNT)
    assert after["latest"]["started_at"] == during["latest"]["started_at"]
    assert after["latest"]["finished_at"] is not None and after["latest"]["with_problems"] is False


async def test_a_report_that_arrives_late_does_not_make_a_finished_run_run_again(client):
    _as(True)
    run_id = uuid.uuid4()
    await _report(client, run_id, "done", account=ACCOUNT)

    await _report(client, run_id, "running", started_at=datetime.now(UTC).isoformat())

    assert (await client.get("/api/admin/owui-sync")).json()["latest"]["status"] == "done"


async def test_a_run_that_could_not_start_says_why(client):
    _as(True)
    await _report(client, uuid.uuid4(), "failed", error="401 Unauthorized")

    latest = (await client.get("/api/admin/owui-sync")).json()["latest"]

    assert (latest["status"], latest["error"], latest["with_problems"]) == ("failed", "401 Unauthorized", True)


@pytest.mark.parametrize(
    "kind, key",
    [("groups", "errors"), ("knowledge_bases", "unlisted"), ("knowledge_bases", "inconsistent"), ("files", "errors")],
)
async def test_a_run_with_objects_in_error_or_inconsistent_vectors_is_flagged(client, kind, key):
    _as(True)
    account = {**ACCOUNT, kind: {**ACCOUNT[kind], key: 2}}
    await _report(client, uuid.uuid4(), "done", account=account)

    assert (await client.get("/api/admin/owui-sync")).json()["latest"]["with_problems"] is True


async def test_a_run_that_never_ended_is_stalled_not_running(client):
    _as(True)
    await _report(client, uuid.uuid4(), "running", started_at=(datetime.now(UTC) - timedelta(hours=7)).isoformat())

    state = (await client.get("/api/admin/owui-sync")).json()

    assert (state["running"], state["latest"]["status"], state["latest"]["stalled"]) == (False, "running", True)


async def test_only_the_latest_runs_are_kept(client, monkeypatch):
    from app.repositories import owui_sync_run_repository

    monkeypatch.setattr(owui_sync_run_repository, "KEPT_RUNS", 2)
    start = datetime.now(UTC) - timedelta(hours=1)
    ids = [uuid.uuid4() for _ in range(4)]
    for index, run_id in enumerate(ids):
        await _report(client, run_id, "running", started_at=(start + timedelta(minutes=index)).isoformat())

    async with async_session_factory() as session:
        kept = {run.run_id for run in (await session.scalars(select(OwuiSyncRun))).all()}
    assert kept == set(ids[2:])


@pytest.mark.parametrize("path", ["/api/admin/owui-sync", "/api/admin/owui-sync/collections"])
async def test_the_account_and_the_collections_are_for_administrators(client, path):
    _as(False)

    assert (await client.get(path)).status_code == 403


async def test_the_copied_collections_are_listed_with_where_each_one_is(client):
    _as(True)
    async with async_session_factory() as session:
        rows = {}
        for name, adopted in (("Copiée", False), ("En reprise", False), ("Reprise", True)):
            collection = Collection(
                owner_id="u",
                name=name,
                source="owui",
                external_id=f"kb-{name}",
                adopted_at=datetime.now(UTC) if adopted else None,
                synced_at=datetime.now(UTC),
                sync_problems=["another model"] if name == "Copiée" else None,
            )
            collection.settings = CollectionSettings(embedding_model="bge")
            session.add(collection)
            await session.flush()
            rows[name] = collection
        session.add(Collection(owner_id="u", name="De Muffin"))
        session.add_all(
            [
                Document(collection_id=rows["Copiée"].id, name="a.pdf", type=DocumentType.FILE, summary="résumé"),
                Document(collection_id=rows["Copiée"].id, name="b.pdf", type=DocumentType.FILE),
            ]
        )
        session.add(
            IndexRebuild(
                collection_id=rows["En reprise"].id,
                status=IndexRebuildStatus.BUILDING,
                target_model="m",
                previous_model="m",
                requested_by="u",
                adopts=True,
            )
        )
        await session.commit()

    listed = (await client.get("/api/admin/owui-sync/collections")).json()

    assert [(c["name"], c["state"]) for c in listed] == [
        ("Copiée", "copied"),
        ("En reprise", "adopting"),
        ("Reprise", "adopted"),
    ]
    copied = listed[0]
    assert (copied["external_id"], copied["document_count"], copied["summary_count"], copied["problems"]) == (
        "kb-Copiée",
        2,
        1,
        ["another model"],
    )
    assert copied["synced_at"] is not None and listed[1]["problems"] == []
