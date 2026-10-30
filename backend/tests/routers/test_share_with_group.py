"""Sharing a collection with a group made in Muffin (#455): its members see it, and change it if the share writes."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.group import Group
from app.repositories.collection_repository import CollectionRepository
from app.repositories.group_repository import GroupRepository
from app.services.editing_rights import require_editable_collection


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.execute(delete(Group))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


def _as(user_id: str, *, admin: bool = False, groups: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=admin, groups=groups or []
    )


async def _effective_groups(user_id: str) -> list[str]:
    async with async_session_factory() as session:
        return await GroupRepository(session).group_ids_of(user_id)


async def _setup(client, permission: str = "read") -> tuple[dict, dict, dict]:
    """A collection and a group of the owner, with julie in it, and the collection shared with the group."""
    _as("owner")
    group = (await client.post("/api/groups", json={"name": "Équipe A"})).json()
    await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "julie-sub"})
    collection = (await client.post("/api/collections")).json()
    share = await client.post(
        f"/api/collections/{collection['id']}/shares",
        json={"subject_type": "group", "group_id": group["id"], "permission": permission},
    )
    return group, collection, share


async def test_a_share_with_a_group_of_muffin_is_active_at_once_and_shows_the_group_name(client):
    group, _, share = await _setup(client)

    assert share.status_code == 201
    body = share.json()
    assert (body["subject_type"], body["status"], body["permission"], body["display_hint"]) == (
        "group",
        "active",
        "read",
        "Équipe A",
    )


async def test_a_member_of_the_group_sees_the_collection_and_a_stranger_does_not(client):
    _, collection, _ = await _setup(client)

    _as("julie-sub", groups=await _effective_groups("julie-sub"))
    seen = (await client.get(f"/api/collections/{collection['id']}")).json()
    assert (seen["is_owner"], seen["can_edit"]) == (False, False)

    _as("stranger")
    assert (await client.get(f"/api/collections/{collection['id']}")).status_code == 404


async def test_a_write_share_with_a_group_lets_its_members_change_the_collection(client):
    _, collection, _ = await _setup(client, "write")

    user = RequestContext(
        user_id="julie-sub", email="", roles=[], is_admin=False, groups=await _effective_groups("julie-sub")
    )
    _as("julie-sub", groups=user.groups)
    assert (await client.get(f"/api/collections/{collection['id']}")).json()["can_edit"] is True
    async with async_session_factory() as session:
        assert await require_editable_collection(CollectionRepository(session), user, collection["id"])


async def test_taking_the_member_out_takes_the_collection_away_from_them(client):
    group, collection, _ = await _setup(client)
    members = (await client.get(f"/api/groups/{group['id']}/members")).json()
    await client.delete(f"/api/groups/{group['id']}/members/{members[0]['id']}")

    _as("julie-sub", groups=await _effective_groups("julie-sub"))
    assert (await client.get(f"/api/collections/{collection['id']}")).status_code == 404


async def test_deleting_the_group_takes_the_collection_away_from_its_members_and_the_share_with_it(client):
    group, collection, _ = await _setup(client)

    await client.delete(f"/api/groups/{group['id']}")

    assert (await client.get(f"/api/collections/{collection['id']}/shares")).json() == []
    _as("julie-sub", groups=await _effective_groups("julie-sub"))
    assert (await client.get(f"/api/collections/{collection['id']}")).status_code == 404


async def test_a_group_the_caller_has_no_part_in_cannot_be_chosen(client):
    group, _, _ = await _setup(client)

    _as("other-owner")
    mine = (await client.post("/api/collections")).json()
    response = await client.post(
        f"/api/collections/{mine['id']}/shares", json={"subject_type": "group", "group_id": group["id"]}
    )

    assert response.status_code == 404


async def test_a_member_may_share_with_the_group_they_are_in(client):
    group, _, _ = await _setup(client)

    _as("julie-sub")
    mine = (await client.post("/api/collections")).json()
    response = await client.post(
        f"/api/collections/{mine['id']}/shares", json={"subject_type": "group", "group_id": group["id"]}
    )

    assert response.status_code == 201


async def test_the_same_group_cannot_be_shared_with_twice(client):
    group, collection, _ = await _setup(client)

    again = await client.post(
        f"/api/collections/{collection['id']}/shares", json={"subject_type": "group", "group_id": group["id"]}
    )

    assert again.status_code == 409


async def test_a_share_names_either_an_identifier_or_a_group(client):
    group, collection, _ = await _setup(client)
    url = f"/api/collections/{collection['id']}/shares"

    assert (await client.post(url, json={"subject_type": "group"})).status_code == 422
    both = {"subject_type": "group", "group_id": group["id"], "identifier": "/team"}
    assert (await client.post(url, json=both)).status_code == 422
    assert (await client.post(url, json={"subject_type": "user", "group_id": group["id"]})).status_code == 422
