"""Read access inherited down the sub-collection tree (#216) - never up it, never sideways."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.core.sharing import hash_identifier, normalize_email, normalize_group
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.repositories.collection_repository import CollectionRepository
from tests.routers.test_collections import _as_user
from tests.routers.test_internal_runs import API_KEY, _headers


@pytest.fixture
async def client():
    _as("owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


def _as(user_id: str, groups: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_user] = _as_user(user_id, f"{user_id}@example.com", groups)


async def _create(client: AsyncClient, name: str, parent_id: str | None = None) -> str:
    body = {"name": name} if parent_id is None else {"name": name, "parent_id": parent_id}
    response = await client.post("/api/collections", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _tree(client: AsyncClient) -> dict[str, str]:
    """root > child > grandchild, plus a sibling of child and an unrelated root."""
    root = await _create(client, "Root")
    child = await _create(client, "Child", root)
    grandchild = await _create(client, "Grandchild", child)
    sibling = await _create(client, "Sibling", root)
    unrelated = await _create(client, "Unrelated")
    return {"root": root, "child": child, "grandchild": grandchild, "sibling": sibling, "unrelated": unrelated}


async def _share_with_user(client: AsyncClient, collection_id: str, user_id: str) -> None:
    email = f"{user_id}@example.com"
    await client.post(f"/api/collections/{collection_id}/shares", json={"subject_type": "user", "identifier": email})
    async with async_session_factory() as session:
        await CollectionRepository(session).resolve_pending_user_shares(
            hash_identifier(normalize_email(email)), user_id
        )
        await session.commit()


async def _share_with_group(client: AsyncClient, collection_id: str, group: str) -> None:
    await client.post(f"/api/collections/{collection_id}/shares", json={"subject_type": "group", "identifier": group})
    async with async_session_factory() as session:
        await CollectionRepository(session).resolve_pending_group_shares(hash_identifier(normalize_group(group)), group)
        await session.commit()


async def _readable_names(client: AsyncClient) -> set[str]:
    return {c["name"] for c in (await client.get("/api/collections")).json()["items"]}


class TestUserShare:
    async def test_share_on_a_parent_reaches_every_descendant(self, client):
        tree = await _tree(client)
        await _share_with_user(client, tree["child"], "viewer")

        _as("viewer")

        assert await _readable_names(client) == {"Child", "Grandchild"}
        assert (await client.get(f"/api/collections/{tree['grandchild']}")).status_code == 200

    async def test_share_on_a_child_never_reaches_its_parent_nor_its_siblings(self, client):
        tree = await _tree(client)
        await _share_with_user(client, tree["child"], "viewer")

        _as("viewer")

        assert (await client.get(f"/api/collections/{tree['root']}")).status_code == 404
        assert (await client.get(f"/api/collections/{tree['sibling']}")).status_code == 404
        assert (await client.get(f"/api/collections/{tree['root']}/children")).status_code == 404

    async def test_pending_share_grants_nothing(self, client):
        tree = await _tree(client)
        await client.post(
            f"/api/collections/{tree['root']}/shares",
            json={"subject_type": "user", "identifier": "viewer@example.com"},
        )

        _as("viewer")

        assert await _readable_names(client) == set()

    async def test_inherited_access_stays_read_only(self, client):
        tree = await _tree(client)
        await _share_with_user(client, tree["root"], "viewer")

        _as("viewer")
        detail = (await client.get(f"/api/collections/{tree['grandchild']}")).json()

        assert detail["is_owner"] is False
        assert (await client.patch(f"/api/collections/{tree['grandchild']}", json={"name": "x"})).status_code == 404
        assert (await client.delete(f"/api/collections/{tree['grandchild']}")).status_code == 404
        assert (await client.get(f"/api/collections/{tree['grandchild']}/shares")).status_code == 404

    async def test_moving_a_collection_out_of_a_shared_subtree_revokes_access(self, client):
        tree = await _tree(client)
        await _share_with_user(client, tree["child"], "viewer")
        await client.patch(f"/api/collections/{tree['grandchild']}", json={"parent_id": None})

        _as("viewer")

        assert await _readable_names(client) == {"Child"}


class TestGroupShare:
    async def test_group_share_on_a_parent_reaches_descendants_for_members_only(self, client):
        tree = await _tree(client)
        await _share_with_group(client, tree["root"], "/team")

        _as("member", groups=["/team"])
        assert await _readable_names(client) == {"Root", "Child", "Grandchild", "Sibling"}

        _as("outsider", groups=["/other-team"])
        assert await _readable_names(client) == set()


class TestPublicParent:
    async def test_public_parent_makes_its_subtree_readable_and_says_so(self, client):
        tree = await _tree(client)
        await client.patch(f"/api/collections/{tree['child']}/visibility", json={"visibility": "public"})

        _as("viewer")
        assert await _readable_names(client) == {"Child", "Grandchild"}

        grandchild = (await client.get(f"/api/collections/{tree['grandchild']}")).json()
        assert grandchild["visibility"] == "private"
        assert grandchild["inherited_public_from"] == {"id": tree["child"], "name": "Child"}

    async def test_owner_sees_the_inherited_public_marker_too(self, client):
        tree = await _tree(client)
        await client.patch(f"/api/collections/{tree['root']}/visibility", json={"visibility": "public"})

        grandchild = (await client.get(f"/api/collections/{tree['grandchild']}")).json()
        root = (await client.get(f"/api/collections/{tree['root']}")).json()
        unrelated = (await client.get(f"/api/collections/{tree['unrelated']}")).json()

        assert grandchild["inherited_public_from"] == {"id": tree["root"], "name": "Root"}
        assert root["inherited_public_from"] is None
        assert unrelated["inherited_public_from"] is None


class TestInheritedSharesListing:
    async def test_lists_own_shares_then_inherited_ones_nearest_first(self, client):
        tree = await _tree(client)
        await _share_with_user(client, tree["root"], "from-root")
        await _share_with_user(client, tree["child"], "from-child")
        await _share_with_user(client, tree["grandchild"], "own")

        shares = (await client.get(f"/api/collections/{tree['grandchild']}/shares")).json()

        assert [s["inherited_from"] for s in shares] == [
            None,
            {"id": tree["child"], "name": "Child"},
            {"id": tree["root"], "name": "Root"},
        ]

    async def test_an_inherited_share_cannot_be_removed_from_the_child(self, client):
        tree = await _tree(client)
        await _share_with_user(client, tree["root"], "viewer")
        inherited = (await client.get(f"/api/collections/{tree['child']}/shares")).json()[0]

        response = await client.delete(f"/api/collections/{tree['child']}/shares/{inherited['id']}")

        assert response.status_code == 404
        assert len((await client.get(f"/api/collections/{tree['root']}/shares")).json()) == 1


class TestAgentRouting:
    async def test_accessible_collections_follow_the_same_inheritance(self, client, monkeypatch):
        monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
        tree = await _tree(client)
        await _share_with_user(client, tree["child"], "viewer")

        response = await client.get("/api/internal/users/viewer/accessible-collections", headers=_headers())

        assert {c["name"] for c in response.json()} == {"Child", "Grandchild"}
