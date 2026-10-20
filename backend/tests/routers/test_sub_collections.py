import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from tests.routers.test_collections import _as_user


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


def _as(user_id: str) -> None:
    app.dependency_overrides[get_current_user] = _as_user(user_id, f"{user_id}@example.com")


async def _create(client: AsyncClient, name: str, parent_id: str | None = None) -> dict:
    body = {"name": name} if parent_id is None else {"name": name, "parent_id": parent_id}
    response = await client.post("/api/collections", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _get(client: AsyncClient, collection_id: str) -> dict:
    return (await client.get(f"/api/collections/{collection_id}")).json()


class TestCreate:
    async def test_root_collection_has_no_place_in_a_tree(self, client):
        root = await _create(client, "Root")

        assert root["parent_id"] is None
        assert root["path"] == []
        assert root["children_count"] == 0

    async def test_creates_a_sub_collection_with_its_path(self, client):
        root = await _create(client, "Root")
        child = await _create(client, "Child", root["id"])
        grandchild = await _create(client, "Grandchild", child["id"])

        assert grandchild["parent_id"] == child["id"]
        assert grandchild["path"] == [{"id": root["id"], "name": "Root"}, {"id": child["id"], "name": "Child"}]
        assert (await _get(client, root["id"]))["children_count"] == 1

    async def test_sub_collection_starts_from_a_copy_of_its_parent_settings(self, client):
        root = await _create(client, "Root")
        await client.patch(
            f"/api/collections/{root['id']}/settings",
            json={
                "chunking_strategy": "fixed",
                "chunk_size": 800,
                "embedding_model": "parent-embedder",
                "generation_models": {"summary": "parent-chat"},
            },
        )

        child = await _create(client, "Child", root["id"])

        assert child["chunking_settings"]["strategy"] == "fixed"
        assert child["chunking_settings"]["chunk_size"] == 800
        assert child["embedding_model"] == "parent-embedder"
        assert child["generation_models"]["summary"] == "parent-chat"
        assert child["reindex_required"] is False

        await client.patch(f"/api/collections/{child['id']}/settings", json={"chunk_size": 300})
        assert (await _get(client, root["id"]))["chunking_settings"]["chunk_size"] == 800

    async def test_unknown_parent_is_a_404(self, client):
        response = await client.post("/api/collections", json={"name": "Child", "parent_id": str(uuid.uuid4())})

        assert response.status_code == 404
        assert response.json()["detail"] == "Parent collection not found"

    async def test_a_readable_but_not_owned_parent_is_a_404(self, client):
        _as("someone-else")
        theirs = await _create(client, "Theirs")
        await client.patch(f"/api/collections/{theirs['id']}/visibility", json={"visibility": "public"})

        _as("owner")
        response = await client.post("/api/collections", json={"name": "Child", "parent_id": theirs["id"]})

        assert response.status_code == 404
        assert (await client.get("/api/collections")).json()["total"] == 1

    async def test_a_temporary_parent_is_a_409(self, client):
        async with async_session_factory() as session:
            temporary = Collection(owner_id="owner", name="Fichiers à ranger", is_temporary=True)
            temporary.settings = CollectionSettings(embedding_model="text-embedding-3-small")
            session.add(temporary)
            await session.commit()

        response = await client.post("/api/collections", json={"name": "Child", "parent_id": str(temporary.id)})

        assert response.status_code == 409


class TestList:
    async def test_flat_by_default_roots_only_on_demand(self, client):
        root = await _create(client, "Root")
        await _create(client, "Child", root["id"])
        await _create(client, "Other root")

        flat = (await client.get("/api/collections")).json()
        roots = (await client.get("/api/collections", params={"roots_only": "true"})).json()

        assert flat["total"] == 3
        assert {c["name"] for c in roots["items"]} == {"Root", "Other root"}
        assert roots["total"] == 2
        assert next(c for c in roots["items"] if c["name"] == "Root")["children_count"] == 1

    async def test_children_lists_direct_children_only(self, client):
        root = await _create(client, "Root")
        child = await _create(client, "Child", root["id"])
        await _create(client, "Other child", root["id"])
        await _create(client, "Grandchild", child["id"])

        response = await client.get(f"/api/collections/{root['id']}/children")

        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert {c["name"] for c in response.json()["items"]} == {"Child", "Other child"}

    async def test_children_of_an_unreadable_collection_is_a_404(self, client):
        root = await _create(client, "Root")

        _as("stranger")
        response = await client.get(f"/api/collections/{root['id']}/children")

        assert response.status_code == 404


class TestMove:
    async def test_moves_under_another_collection(self, client):
        root = await _create(client, "Root")
        other = await _create(client, "Other")

        response = await client.patch(f"/api/collections/{other['id']}", json={"parent_id": root["id"]})

        assert response.status_code == 200
        assert response.json()["parent_id"] == root["id"]

    async def test_explicit_null_moves_back_to_the_root(self, client):
        root = await _create(client, "Root")
        child = await _create(client, "Child", root["id"])

        response = await client.patch(f"/api/collections/{child['id']}", json={"parent_id": None})

        assert response.json()["parent_id"] is None
        assert response.json()["path"] == []

    async def test_leaving_parent_id_out_keeps_the_parent(self, client):
        root = await _create(client, "Root")
        child = await _create(client, "Child", root["id"])

        response = await client.patch(f"/api/collections/{child['id']}", json={"name": "Renamed"})

        assert response.json()["name"] == "Renamed"
        assert response.json()["parent_id"] == root["id"]

    async def test_moving_under_a_descendant_is_a_409_and_changes_nothing(self, client):
        root = await _create(client, "Root")
        child = await _create(client, "Child", root["id"])

        response = await client.patch(
            f"/api/collections/{root['id']}", json={"parent_id": child["id"], "name": "Should not apply"}
        )

        assert response.status_code == 409
        detail = await _get(client, root["id"])
        assert detail["parent_id"] is None
        assert detail["name"] == "Root"

    async def test_moving_under_itself_is_a_409(self, client):
        root = await _create(client, "Root")

        response = await client.patch(f"/api/collections/{root['id']}", json={"parent_id": root["id"]})

        assert response.status_code == 409

    async def test_moving_under_someone_elses_collection_is_a_404(self, client):
        _as("someone-else")
        theirs = await _create(client, "Theirs")

        _as("owner")
        mine = await _create(client, "Mine")
        response = await client.patch(f"/api/collections/{mine['id']}", json={"parent_id": theirs["id"]})

        assert response.status_code == 404
        assert response.json()["detail"] == "Parent collection not found"


class TestTreeVisibility:
    async def test_a_collection_readable_on_its_own_never_reveals_the_tree_above_it(self, client):
        root = await _create(client, "Private root")
        child = await _create(client, "Public child", root["id"])
        await client.patch(f"/api/collections/{child['id']}/visibility", json={"visibility": "public"})

        _as("viewer")
        detail = await _get(client, child["id"])

        assert detail["parent_id"] is None
        assert detail["path"] == []

    async def test_children_count_ignores_unreadable_children(self, client):
        # Until rights are inherited down the tree (#216), a public parent doesn't make its
        # private child readable - that test will flip with it.
        root = await _create(client, "Public root")
        await client.patch(f"/api/collections/{root['id']}/visibility", json={"visibility": "public"})
        await _create(client, "Private child", root["id"])

        _as("viewer")
        detail = await _get(client, root["id"])

        assert detail["children_count"] == 0
