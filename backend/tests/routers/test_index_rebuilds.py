"""Blue/green rebuild of a collection's index (#12), through the HTTP API with an in-memory stand-in
for Qdrant: what the tests check is what is asked of the two indexes and when."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.index_rebuild import IndexRebuild, IndexRebuildStatus
from app.models.qa import QaOrigin, QaPair
from app.models.task import Task

API_KEY = "test-worker-key"
OLD_MODEL = "text-embedding-3-small"
NEW_MODEL = "text-embedding-3-large"


class FakeIndexes:
    """chunks_<id> (active) and chunks_<id>_next (being built), as dicts of point id -> point."""

    def __init__(self) -> None:
        self.active: dict[str, dict] = {}
        self.next: dict[str, dict] | None = None

    def _index(self, next_index: bool) -> dict[str, dict]:
        if next_index:
            if self.next is None:
                self.next = {}
            return self.next
        return self.active

    def list_points(self, collection_id, *, next_index):
        index = self.next if next_index else self.active
        return {point_id: dict(point) for point_id, point in (index or {}).items()}

    def upsert_points(self, collection_id, points, model, *, next_index):
        index = self._index(next_index)
        for kind, point_id, text, _embedding in points:
            index[str(point_id)] = {"kind": kind, "text": text, "model": model}

    def delete_points(self, collection_id, point_ids, *, next_index):
        index = self.next if next_index else self.active
        for point_id in point_ids:
            (index or {}).pop(point_id, None)

    def next_index_exists(self, collection_id):
        return self.next is not None

    def delete_next_index(self, collection_id):
        self.next = None

    def swap_with_next(self, collection_id):
        self.active, self.next = self.next or {}, self.active


@pytest.fixture(autouse=True)
def _worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
def indexes():
    fake = FakeIndexes()
    namespace = SimpleNamespace(
        **{
            name: getattr(fake, name)
            for name in (
                "list_points",
                "upsert_points",
                "delete_points",
                "next_index_exists",
                "delete_next_index",
                "swap_with_next",
            )
        }
    )
    with patch("app.services.index_rebuild_service.vector_store", namespace):
        yield fake


@pytest.fixture
def enqueued():
    counter = iter(range(1, 100))
    with patch(
        "app.services.index_rebuild_service.enqueue_rebuild_index",
        side_effect=lambda _id: f"task-{uuid.uuid4()}-{next(counter)}",
    ) as mock:
        yield mock


@pytest.fixture
async def client(indexes, enqueued):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


def _worker() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _collection_with_content(client) -> dict[str, uuid.UUID]:
    """A collection owned by the test user: one document with a summary and two chunks, one generated
    QA pair and one golden one (which never goes in an index)."""
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(embedding_model=OLD_MODEL)
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="a.pdf", type="url", summary="A summary")
        session.add(document)
        await session.flush()
        chunk_1 = Chunk(document_id=document.id, index=0, text="first chunk", token_count=2)
        chunk_2 = Chunk(document_id=document.id, index=1, text="second chunk", token_count=2)
        qa = QaPair(
            collection_id=collection.id,
            document_id=document.id,
            question="Why?",
            answer="Because",
            origin=QaOrigin.GENERATED,
        )
        golden = QaPair(
            collection_id=collection.id,
            document_id=document.id,
            question="Golden?",
            answer="Yes",
            origin=QaOrigin.MANUAL,
            golden=True,
            validated=True,
        )
        session.add_all([chunk_1, chunk_2, qa, golden])
        await session.commit()
        return {
            "collection": collection.id,
            "document": document.id,
            "chunk_1": chunk_1.id,
            "chunk_2": chunk_2.id,
            "qa": qa.id,
        }


async def _choose_new_model(client, collection_id) -> None:
    response = await client.patch(f"/api/collections/{collection_id}/settings", json={"embedding_model": NEW_MODEL})
    assert response.status_code == 200


async def _start(client, collection_id) -> dict:
    response = await client.post(f"/api/collections/{collection_id}/documents/reindex")
    assert response.status_code == 202, response.text
    return response.json()


async def _plan(client, rebuild_id) -> dict:
    response = await client.get(f"/api/internal/index-rebuilds/{rebuild_id}/plan", headers=_worker())
    assert response.status_code == 200
    return response.json()


async def _embed_everything(client, rebuild_id) -> dict:
    plan = await _plan(client, rebuild_id)
    points = [{**point, "embedding": [0.1, 0.2]} for point in plan["points"]]
    response = await client.post(
        f"/api/internal/index-rebuilds/{rebuild_id}/vectors",
        headers=_worker(),
        json={"model": plan["model"], "points": points},
    )
    assert response.status_code == 200
    return response.json()


async def _swap(client, rebuild_id) -> bool:
    response = await client.post(f"/api/internal/index-rebuilds/{rebuild_id}/swap", headers=_worker())
    assert response.status_code == 200
    return response.json()["swapped"]


async def _settings(collection_id) -> CollectionSettings:
    async with async_session_factory() as session:
        return (
            await session.execute(select(CollectionSettings).where(CollectionSettings.collection_id == collection_id))
        ).scalar_one()


# -- the lock -----------------------------------------------------------------------------------


async def test_starting_a_rebuild_queues_it_on_its_own_task(client, enqueued):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])

    rebuild = await _start(client, ids["collection"])

    assert rebuild["status"] == "building"
    assert rebuild["target_model"] == NEW_MODEL
    assert rebuild["previous_model"] == OLD_MODEL
    enqueued.assert_called_once_with(rebuild["id"])


async def test_a_second_rebuild_is_refused_while_one_is_in_progress(client, enqueued):
    ids = await _collection_with_content(client)
    await _start(client, ids["collection"])

    response = await client.post(f"/api/collections/{ids['collection']}/documents/reindex")

    assert response.status_code == 409
    assert enqueued.call_count == 1


async def test_the_lock_also_holds_while_the_swap_awaits_validation(client):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])
    assert await _swap(client, rebuild["id"]) is True

    response = await client.post(f"/api/collections/{ids['collection']}/documents/reindex")

    assert response.status_code == 409


async def test_starting_a_rebuild_on_an_unknown_collection_is_a_404(client):
    response = await client.post(f"/api/collections/{uuid.uuid4()}/documents/reindex")

    assert response.status_code == 404


async def test_a_collection_copied_from_another_system_is_never_rebuilt(client, enqueued):
    """Its vectors are that system's, in its Qdrant: Muffin has no index of its own to rebuild (#453)."""
    ids = await _collection_with_content(client)
    async with async_session_factory() as session:
        collection = await session.get(Collection, ids["collection"])
        collection.source, collection.external_id = "owui", "kb1"
        await session.commit()

    response = await client.post(f"/api/collections/{ids['collection']}/documents/reindex")

    assert response.status_code == 409
    enqueued.assert_not_called()


async def test_a_collection_you_do_not_own_cannot_be_rebuilt(client):
    ids = await _collection_with_content(client)
    async with async_session_factory() as session:
        collection = await session.get(Collection, ids["collection"])
        collection.owner_id = "someone-else"
        await session.commit()

    response = await client.post(f"/api/collections/{ids['collection']}/documents/reindex")

    assert response.status_code == 404


async def test_the_worker_routes_need_the_api_key(client):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])

    assert (await client.get(f"/api/internal/index-rebuilds/{rebuild['id']}/plan")).status_code == 401


# -- the plan -----------------------------------------------------------------------------------


async def test_the_plan_lists_chunks_summaries_and_generated_qa_but_never_golden_ones(client):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])

    plan = await _plan(client, rebuild["id"])

    assert plan["status"] == "building"
    assert plan["remaining"] == 4
    assert {(point["kind"], point["text"]) for point in plan["points"]} == {
        ("chunk", "first chunk"),
        ("chunk", "second chunk"),
        ("summary", "A summary"),
        ("qa", "Why?"),
    }


async def test_progress_is_kept_in_the_database(client):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])

    await _plan(client, rebuild["id"])

    latest = (await client.get(f"/api/collections/{ids['collection']}/index-rebuild")).json()
    assert (latest["total_points"], latest["done_points"]) == (4, 4)


async def test_a_resumed_job_only_gets_what_is_still_missing(client, indexes):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])
    rebuild = await _start(client, ids["collection"])
    first_plan = await _plan(client, rebuild["id"])
    done = first_plan["points"][:3]
    await client.post(
        f"/api/internal/index-rebuilds/{rebuild['id']}/vectors",
        headers=_worker(),
        json={"model": NEW_MODEL, "points": [{**point, "embedding": [0.1]} for point in done]},
    )

    # The job crashed here; the redelivered one starts from a fresh plan.
    plan = await _plan(client, rebuild["id"])

    assert plan["remaining"] == 1
    assert {point["id"] for point in plan["points"]}.isdisjoint({point["id"] for point in done})


async def test_a_vector_made_with_another_model_is_made_again(client, indexes):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])
    rebuild = await _start(client, ids["collection"])
    indexes.next = {
        str(ids["chunk_1"]): {"kind": "chunk", "text": "first chunk", "model": OLD_MODEL},
    }

    plan = await _plan(client, rebuild["id"])

    assert str(ids["chunk_1"]) in {point["id"] for point in plan["points"]}


async def test_points_that_no_longer_exist_are_removed_from_the_index_being_built(client, indexes):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])
    gone = str(uuid.uuid4())
    indexes.next = {gone: {"kind": "chunk", "text": "deleted since", "model": NEW_MODEL}}

    await _plan(client, rebuild["id"])

    assert gone not in indexes.next


# -- a text changed during the build ------------------------------------------------------------


async def test_a_vector_made_from_an_outdated_text_never_overwrites_a_newer_one(client, indexes):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])
    rebuild = await _start(client, ids["collection"])
    plan = await _plan(client, rebuild["id"])
    chunk = next(point for point in plan["points"] if point["id"] == str(ids["chunk_1"]))

    async with async_session_factory() as session:
        (await session.get(Chunk, ids["chunk_1"])).text = "first chunk, edited"
        await session.commit()
    response = await client.post(
        f"/api/internal/index-rebuilds/{rebuild['id']}/vectors",
        headers=_worker(),
        json={"model": NEW_MODEL, "points": [{**chunk, "embedding": [0.1]}]},
    )

    assert response.json() == {"stored": 0}
    assert str(ids["chunk_1"]) not in (indexes.next or {})
    # ...and the next plan hands the new text out.
    again = await _plan(client, rebuild["id"])
    assert {"id": str(ids["chunk_1"]), "kind": "chunk", "text": "first chunk, edited"} in again["points"]


async def test_vectors_made_with_the_wrong_model_are_refused(client):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])

    response = await client.post(
        f"/api/internal/index-rebuilds/{rebuild['id']}/vectors",
        headers=_worker(),
        json={"model": "some-other-model", "points": []},
    )

    assert response.status_code == 409


# -- the swap -----------------------------------------------------------------------------------


async def test_the_new_index_is_swapped_in_once_complete_and_the_model_follows(client, indexes):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])
    indexes.active = {str(ids["chunk_1"]): {"kind": "chunk", "text": "first chunk", "model": OLD_MODEL}}
    rebuild = await _start(client, ids["collection"])
    settings = await _settings(ids["collection"])
    assert (settings.index_embedding_model, settings.reindex_required) == (OLD_MODEL, True)

    # While it builds, the active index is untouched and still answers.
    await _embed_everything(client, rebuild["id"])
    assert set(indexes.active) == {str(ids["chunk_1"])}
    assert indexes.active[str(ids["chunk_1"])]["model"] == OLD_MODEL

    assert await _swap(client, rebuild["id"]) is True

    assert {point["model"] for point in indexes.active.values()} == {NEW_MODEL}
    assert len(indexes.active) == 4
    assert set(indexes.next) == {str(ids["chunk_1"])}  # the old one, kept for a rollback
    settings = await _settings(ids["collection"])
    assert (settings.index_embedding_model, settings.reindex_required) == (None, False)
    latest = (await client.get(f"/api/collections/{ids['collection']}/index-rebuild")).json()
    assert latest["status"] == "swapped"


async def test_it_is_not_swapped_while_a_document_added_since_is_missing(client, indexes):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])
    async with async_session_factory() as session:
        session.add(Chunk(document_id=ids["document"], index=2, text="added during the build", token_count=4))
        await session.commit()

    assert await _swap(client, rebuild["id"]) is False
    assert indexes.active == {}

    await _embed_everything(client, rebuild["id"])
    assert await _swap(client, rebuild["id"]) is True
    assert any(point["text"] == "added during the build" for point in indexes.active.values())


async def test_what_is_written_after_the_swap_is_caught_by_the_next_plan(client, indexes):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])
    await _swap(client, rebuild["id"])
    async with async_session_factory() as session:
        session.add(Chunk(document_id=ids["document"], index=2, text="in the gap", token_count=2))
        await session.commit()

    plan = await _plan(client, rebuild["id"])

    assert plan["status"] == "swapped"
    assert [point["text"] for point in plan["points"]] == ["in the gap"]


async def test_a_model_changed_again_during_the_build_still_needs_a_reindex(client):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])
    rebuild = await _start(client, ids["collection"])
    await client.patch(f"/api/collections/{ids['collection']}/settings", json={"embedding_model": "a-third-model"})
    await _embed_everything(client, rebuild["id"])

    await _swap(client, rebuild["id"])

    settings = await _settings(ids["collection"])
    assert settings.embedding_model == "a-third-model"
    assert (settings.index_embedding_model, settings.reindex_required) == (NEW_MODEL, True)


async def test_an_empty_collection_just_changes_its_model(client, indexes):
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Empty", description="")
        collection.settings = CollectionSettings(embedding_model=OLD_MODEL)
        session.add(collection)
        await session.commit()
        collection_id = collection.id
    await _choose_new_model(client, collection_id)
    rebuild = await _start(client, collection_id)

    assert await _swap(client, rebuild["id"]) is True

    settings = await _settings(collection_id)
    assert (settings.index_embedding_model, settings.reindex_required) == (None, False)


# -- while the new model is not in the index yet --------------------------------------------------


async def test_search_keeps_using_the_indexs_model_until_it_is_rebuilt(client):
    ids = await _collection_with_content(client)

    response = await client.patch(f"/api/collections/{ids['collection']}/settings", json={"embedding_model": NEW_MODEL})

    body = response.json()
    assert (body["embedding_model"], body["index_embedding_model"], body["reindex_required"]) == (
        NEW_MODEL,
        OLD_MODEL,
        True,
    )
    from app.repositories.collection_repository import CollectionRepository

    async with async_session_factory() as session:
        models = await CollectionRepository(session).get_embedding_models([ids["collection"]])
    assert models == {ids["collection"]: OLD_MODEL}


async def test_going_back_to_the_indexs_model_cancels_the_pending_change(client):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])

    await client.patch(f"/api/collections/{ids['collection']}/settings", json={"embedding_model": OLD_MODEL})

    settings = await _settings(ids["collection"])
    assert (settings.index_embedding_model, settings.reindex_required) == (None, False)


# -- validation, rollback, failure ----------------------------------------------------------------


async def test_validating_the_swap_deletes_the_old_index(client, indexes):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])
    await _swap(client, rebuild["id"])
    assert indexes.next is not None

    response = await client.post(f"/api/collections/{ids['collection']}/index-rebuild/{rebuild['id']}/finalize")

    assert response.status_code == 200
    assert response.json()["status"] == "finalized"
    assert indexes.next is None
    # The lock is released.
    await _start(client, ids["collection"])


async def test_the_old_index_is_not_deleted_before_it_is_validated(client, indexes):
    ids = await _collection_with_content(client)
    indexes.active = {str(ids["chunk_1"]): {"kind": "chunk", "text": "first chunk", "model": OLD_MODEL}}
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])

    await _swap(client, rebuild["id"])

    assert set(indexes.next) == {str(ids["chunk_1"])}


async def test_only_a_swapped_rebuild_can_be_validated_or_rolled_back(client):
    ids = await _collection_with_content(client)
    rebuild = await _start(client, ids["collection"])

    finalize = await client.post(f"/api/collections/{ids['collection']}/index-rebuild/{rebuild['id']}/finalize")
    rollback = await client.post(f"/api/collections/{ids['collection']}/index-rebuild/{rebuild['id']}/rollback")

    assert (finalize.status_code, rollback.status_code) == (409, 409)


async def test_rolling_back_returns_to_the_old_index_and_its_model(client, indexes, enqueued):
    ids = await _collection_with_content(client)
    await _choose_new_model(client, ids["collection"])
    indexes.active = {str(ids["chunk_1"]): {"kind": "chunk", "text": "first chunk", "model": OLD_MODEL}}
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])
    await _swap(client, rebuild["id"])

    response = await client.post(f"/api/collections/{ids['collection']}/index-rebuild/{rebuild['id']}/rollback")

    assert response.status_code == 200
    assert response.json()["status"] == "rolled_back"
    assert set(indexes.active) == {str(ids["chunk_1"])}
    assert indexes.next is None
    settings = await _settings(ids["collection"])
    # The chosen model stays configured: the collection still asks for a rebuild.
    assert (settings.embedding_model, settings.index_embedding_model, settings.reindex_required) == (
        NEW_MODEL,
        OLD_MODEL,
        True,
    )
    # The old index is brought up to date by the job, once.
    assert enqueued.call_count == 2
    plan = await _plan(client, rebuild["id"])
    assert plan["model"] == OLD_MODEL
    assert plan["status"] == "rolled_back"
    # The chunk the old index already held is up to date; the rest was never in it.
    assert plan["remaining"] == 3


async def test_a_failed_build_leaves_the_active_index_alone_and_frees_the_lock(client, indexes):
    ids = await _collection_with_content(client)
    indexes.active = {str(ids["chunk_1"]): {"kind": "chunk", "text": "first chunk", "model": OLD_MODEL}}
    rebuild = await _start(client, ids["collection"])
    await _embed_everything(client, rebuild["id"])

    response = await client.post(
        f"/api/internal/index-rebuilds/{rebuild['id']}/fail", headers=_worker(), json={"error": "the hub is down"}
    )

    assert response.status_code == 200
    assert set(indexes.active) == {str(ids["chunk_1"])}
    assert indexes.next is None
    latest = (await client.get(f"/api/collections/{ids['collection']}/index-rebuild")).json()
    assert (latest["status"], latest["error"]) == ("failed", "the hub is down")
    await _start(client, ids["collection"])
    async with async_session_factory() as session:
        statuses = (await session.execute(select(IndexRebuild.status))).scalars().all()
    assert sorted(statuses) == sorted([IndexRebuildStatus.FAILED, IndexRebuildStatus.BUILDING])


async def test_a_collection_that_never_had_a_rebuild_has_none(client):
    ids = await _collection_with_content(client)

    response = await client.get(f"/api/collections/{ids['collection']}/index-rebuild")

    assert response.status_code == 200
    assert response.json() is None
