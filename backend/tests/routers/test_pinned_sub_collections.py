"""Pinning a collection brings its sub-collections along (#220)."""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.conversation import Conversation
from app.models.run import Run
from app.models.task import Task
from app.services import run_service
from tests.routers.test_collections import _as_user
from tests.routers.test_internal_runs import API_KEY, _headers


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection))
        await session.commit()


async def _collection(client: AsyncClient, name: str, parent_id: str | None = None) -> str:
    body = {"name": name} if parent_id is None else {"name": name, "parent_id": parent_id}
    response = await client.post("/api/collections", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _run(client: AsyncClient, collection_ids: list[str], **extra) -> Run:
    with patch("app.services.run_service.agent_runner.start"):
        response = await client.post("/api/runs", json={"query": "q", "collection_ids": collection_ids, **extra})
    assert response.status_code == 202, response.text
    async with async_session_factory() as session:
        return await session.get(Run, uuid.UUID(response.json()["id"]))


async def _tree(client: AsyncClient) -> dict[str, str]:
    """Root > Child > Grandchild, Root > Sibling, plus an unrelated collection."""
    root = await _collection(client, "Root")
    child = await _collection(client, "Child", root)
    return {
        "root": root,
        "child": child,
        "grandchild": await _collection(client, "Grandchild", child),
        "sibling": await _collection(client, "Sibling", root),
        "unrelated": await _collection(client, "Unrelated"),
    }


class TestPinning:
    async def test_pinning_a_parent_pins_its_whole_subtree(self, client):
        tree = await _tree(client)

        run = await _run(client, [tree["root"]])

        assert set(run.pinned_collection_ids) == {tree["root"], tree["child"], tree["grandchild"], tree["sibling"]}
        assert run.unexplored_collection_ids is None

    async def test_pinning_a_child_never_pins_its_parent_or_siblings(self, client):
        tree = await _tree(client)

        run = await _run(client, [tree["child"]])

        assert set(run.pinned_collection_ids) == {tree["child"], tree["grandchild"]}

    async def test_unchecking_include_descendants_pins_only_what_was_chosen(self, client):
        tree = await _tree(client)

        run = await _run(client, [tree["root"]], include_descendants=False)

        assert run.pinned_collection_ids == [tree["root"]]

    async def test_overlapping_pins_count_once(self, client):
        tree = await _tree(client)

        run = await _run(client, [tree["root"], tree["child"]])

        assert len(run.pinned_collection_ids) == len(set(run.pinned_collection_ids)) == 4

    async def test_a_collection_the_user_cannot_read_is_not_expanded(self, client):
        app.dependency_overrides[get_current_user] = _as_user("someone-else", "else@example.com")
        theirs = await _collection(client, "Theirs")
        await _collection(client, "Their child", theirs)

        app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
        run = await _run(client, [theirs])

        # Kept as sent (the worker ignores what isn't accessible), but nothing below it leaks in.
        assert run.pinned_collection_ids == [theirs]

    async def test_a_shared_parent_brings_its_sub_collections_along(self, client):
        app.dependency_overrides[get_current_user] = _as_user("someone-else", "else@example.com")
        parent = await _collection(client, "Public parent")
        child = await _collection(client, "Private child", parent)
        await client.patch(f"/api/collections/{parent}/visibility", json={"visibility": "public"})

        app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
        run = await _run(client, [parent])

        assert set(run.pinned_collection_ids) == {parent, child}


class TestLimit:
    async def test_the_nearest_sub_collections_are_pinned_and_the_rest_stays_explorable(self, client, monkeypatch):
        monkeypatch.setattr(run_service._run_settings, "PINNED_DESCENDANTS_LIMIT", 2)
        root = await _collection(client, "Root")
        near_a = await _collection(client, "A", root)
        near_b = await _collection(client, "B", root)
        deep = await _collection(client, "Deep", near_a)
        deeper = await _collection(client, "Deeper", deep)

        run = await _run(client, [root])

        assert set(run.pinned_collection_ids) == {root, near_a, near_b}
        # Both leftovers hang below A, the nearest pinned ancestor: that's where "go further" resumes.
        assert run.unexplored_collection_ids == [near_a]
        assert deep not in run.pinned_collection_ids and deeper not in run.pinned_collection_ids

    async def test_leftovers_under_the_pinned_root_itself_report_the_root(self, client, monkeypatch):
        monkeypatch.setattr(run_service._run_settings, "PINNED_DESCENDANTS_LIMIT", 1)
        root = await _collection(client, "Root")
        await _collection(client, "A", root)
        await _collection(client, "B", root)

        run = await _run(client, [root])

        assert len(run.pinned_collection_ids) == 2
        assert run.unexplored_collection_ids == [root]

    async def test_nothing_is_left_over_within_the_limit(self, client, monkeypatch):
        monkeypatch.setattr(run_service._run_settings, "PINNED_DESCENDANTS_LIMIT", 3)
        tree = await _tree(client)

        run = await _run(client, [tree["root"]])

        assert run.unexplored_collection_ids is None

    async def test_the_worker_receives_the_leftovers_as_its_starting_frontier(self, client, monkeypatch):
        monkeypatch.setattr(run_service._run_settings, "PINNED_DESCENDANTS_LIMIT", 1)
        root = await _collection(client, "Root")
        await _collection(client, "A", root)
        await _collection(client, "B", root)
        run = await _run(client, [root])

        body = (await client.get(f"/api/internal/runs/{run.id}", headers=_headers())).json()

        assert body["unexplored_collection_ids"] == [root]
