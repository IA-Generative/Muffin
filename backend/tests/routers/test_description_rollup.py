"""Scheduling of the parent-description rollup (#218): what triggers it, and the grouping window."""

from unittest.mock import MagicMock

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.task import Task
from app.services import description_rollup_service
from app.services.description_rollup_service import ROLLUP_DELAY_SECONDS, DescriptionRollupService
from tests.routers.test_collections import _as_user
from tests.routers.test_internal_runs import API_KEY, _headers


@pytest.fixture
def enqueue(monkeypatch) -> MagicMock:
    monkeypatch.setattr(description_rollup_service, "_redis", fakeredis.FakeRedis(decode_responses=True))
    fake_enqueue = MagicMock(side_effect=lambda collection_id, countdown: f"celery-{collection_id}")
    monkeypatch.setattr(description_rollup_service, "enqueue_rollup_collection_description", fake_enqueue)
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
    return fake_enqueue


@pytest.fixture
async def client(enqueue):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


async def _create(client: AsyncClient, name: str, parent_id: str | None = None, description: str = "") -> str:
    body = {"name": name, "description": description}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = await client.post("/api/collections", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _scheduled(enqueue: MagicMock) -> list[str]:
    return [call.args[0] for call in enqueue.call_args_list]


class TestSchedule:
    async def test_a_root_has_nothing_to_schedule(self, client, enqueue):
        async with async_session_factory() as session:
            await DescriptionRollupService(session).schedule(None)

        enqueue.assert_not_called()

    async def test_schedules_once_per_window_with_a_delay_and_a_task_row(self, client, enqueue):
        parent = await _create(client, "Parent")

        async with async_session_factory() as session:
            service = DescriptionRollupService(session)
            collection = await session.get(Collection, parent)
            await service.schedule(collection.id)
            await service.schedule(collection.id)
            await session.commit()

        enqueue.assert_called_once_with(parent, ROLLUP_DELAY_SECONDS)
        async with async_session_factory() as session:
            task = await session.scalar(select(Task).where(Task.collection_id == collection.id))
        assert task.celery_task_id == f"celery-{parent}"
        assert task.owner_id == "owner"

    async def test_a_scheduling_failure_never_raises(self, client, enqueue, monkeypatch):
        parent = await _create(client, "Parent")
        broken_redis = MagicMock()
        broken_redis.set.side_effect = ConnectionError("redis down")
        monkeypatch.setattr(description_rollup_service, "_redis", broken_redis)

        async with async_session_factory() as session:
            await DescriptionRollupService(session).schedule((await session.get(Collection, parent)).id)

        enqueue.assert_not_called()


class TestPipelineTriggers:
    async def test_a_changed_child_description_schedules_its_parent(self, client, enqueue):
        parent = await _create(client, "Parent")
        child = await _create(client, "Child", parent)

        await client.patch(
            f"/api/internal/collections/{child}/description", headers=_headers(), json={"description": "New."}
        )

        assert _scheduled(enqueue) == [parent]

    async def test_an_unchanged_description_stops_the_propagation(self, client, enqueue):
        parent = await _create(client, "Parent")
        child = await _create(client, "Child", parent, description="Same.")

        await client.patch(
            f"/api/internal/collections/{child}/description", headers=_headers(), json={"description": "Same."}
        )

        enqueue.assert_not_called()

    async def test_a_root_description_change_schedules_nothing(self, client, enqueue):
        root = await _create(client, "Root")

        await client.patch(
            f"/api/internal/collections/{root}/description", headers=_headers(), json={"description": "New."}
        )

        enqueue.assert_not_called()

    async def test_metadata_lists_described_sub_collections(self, client, enqueue):
        parent = await _create(client, "Parent")
        await _create(client, "Leave", parent, description="Leave policies.")
        await _create(client, "Empty", parent)

        metadata = (await client.get(f"/api/internal/collections/{parent}/metadata", headers=_headers())).json()

        assert metadata["sub_collections"] == [{"name": "Leave", "description": "Leave policies."}]


class TestUserTriggers:
    async def test_a_manual_description_edit_schedules_the_parent(self, client, enqueue):
        parent = await _create(client, "Parent")
        child = await _create(client, "Child", parent)

        await client.patch(f"/api/collections/{child}", json={"description": "Written by hand."})

        assert _scheduled(enqueue) == [parent]

    async def test_renaming_without_touching_the_description_schedules_nothing(self, client, enqueue):
        parent = await _create(client, "Parent")
        child = await _create(client, "Child", parent, description="Described.")

        await client.patch(f"/api/collections/{child}", json={"name": "Renamed", "description": "Described."})

        enqueue.assert_not_called()

    async def test_moving_a_described_collection_schedules_both_parents(self, client, enqueue):
        old_parent = await _create(client, "Old parent")
        new_parent = await _create(client, "New parent")
        child = await _create(client, "Child", old_parent, description="Described.")

        await client.patch(f"/api/collections/{child}", json={"parent_id": new_parent})

        assert sorted(_scheduled(enqueue)) == sorted([old_parent, new_parent])

    async def test_moving_an_undescribed_collection_schedules_nothing(self, client, enqueue):
        old_parent = await _create(client, "Old parent")
        new_parent = await _create(client, "New parent")
        child = await _create(client, "Child", old_parent)

        await client.patch(f"/api/collections/{child}", json={"parent_id": new_parent})

        enqueue.assert_not_called()

    async def test_deleting_a_described_child_schedules_its_parent(self, client, enqueue, monkeypatch):
        from app.services import collection_service

        monkeypatch.setattr(collection_service.storage, "delete_objects", MagicMock())
        monkeypatch.setattr(collection_service.vector_store, "delete_collection", MagicMock())
        parent = await _create(client, "Parent")
        child = await _create(client, "Child", parent, description="Described.")

        assert (await client.delete(f"/api/collections/{child}")).status_code == 204

        assert _scheduled(enqueue) == [parent]
