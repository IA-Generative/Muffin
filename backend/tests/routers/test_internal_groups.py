"""The groups copied from Open WebUI (#453): written by the worker, and what puts a member in them."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import factory, worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionShare, ShareStatus, ShareSubjectType
from app.models.group import Group, GroupMember
from app.repositories.collection_repository import CollectionRepository
from app.repositories.group_repository import GroupRepository

API_KEY = "test-worker-key"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Group))
        await session.commit()


async def _members(group_id) -> set[str]:
    async with async_session_factory() as session:
        return set(await session.scalars(select(GroupMember.user_id).where(GroupMember.group_id == group_id)))


async def _put(client, external_id="g1", **body):
    return await client.put(
        f"/api/internal/groups/owui/{external_id}", headers=HEADERS, json={"name": "Équipe A", "member_ids": [], **body}
    )


async def test_the_worker_key_is_required(client):
    assert (await client.put("/api/internal/groups/owui/g1", json={"name": "x"})).status_code == 401


async def test_a_new_group_is_created_with_its_members(client):
    response = await _put(client, member_ids=["sub-1", "sub-2"])

    assert response.status_code == 200
    body = response.json()
    assert (body["created"], body["members_added"], body["members_removed"]) == (True, 2, 0)
    assert await _members(body["id"]) == {"sub-1", "sub-2"}


async def test_syncing_again_makes_no_change(client):
    first = (await _put(client, member_ids=["sub-1"])).json()
    second = (await _put(client, member_ids=["sub-1"])).json()

    assert second["id"] == first["id"]
    assert (second["created"], second["members_added"], second["members_removed"]) == (False, 0, 0)


async def test_members_follow_the_other_system(client):
    first = (await _put(client, member_ids=["sub-1", "sub-2"])).json()
    second = (await _put(client, name="Équipe A2", member_ids=["sub-2", "sub-3"])).json()

    assert (second["members_added"], second["members_removed"]) == (1, 1)
    assert await _members(first["id"]) == {"sub-2", "sub-3"}
    async with async_session_factory() as session:
        assert (await session.get(Group, first["id"])).name == "Équipe A2"


async def test_the_groups_made_in_muffin_are_not_the_synchronisations_to_write(client):
    response = await client.put("/api/internal/groups/muffin/g1", headers=HEADERS, json={"name": "x"})
    assert response.status_code == 400


async def test_listing_and_dropping_the_copies(client):
    await _put(client, "g1")
    await _put(client, "g2")

    assert sorted((await client.get("/api/internal/groups/owui", headers=HEADERS)).json()) == ["g1", "g2"]
    assert (await client.delete("/api/internal/groups/owui/g1", headers=HEADERS)).status_code == 204
    assert (await client.delete("/api/internal/groups/owui/g1", headers=HEADERS)).status_code == 404
    assert (await client.get("/api/internal/groups/owui", headers=HEADERS)).json() == ["g2"]


async def test_a_member_has_the_group_next_to_those_of_their_token(client, monkeypatch):
    group_id = (await _put(client, member_ids=["sub-1"])).json()["id"]
    token = RequestContext(user_id="sub-1", email="", roles=[], is_admin=False, groups=["/muffin-dev-team"])
    monkeypatch.setattr(factory, "TokenVerifier", lambda request: token)

    async with async_session_factory() as session:
        user = await get_current_user(context=factory.get_token_identity(None), db=session)

    assert user.groups == ["/muffin-dev-team", group_id]


async def test_a_collection_shared_with_a_copied_group_reaches_its_members(client):
    group_id = (await _put(client, member_ids=["sub-1"])).json()["id"]
    async with async_session_factory() as session:
        collection = Collection(owner_id="owner", name="Shared")
        session.add(collection)
        await session.flush()
        session.add(
            CollectionShare(
                collection_id=collection.id,
                subject_type=ShareSubjectType.GROUP,
                status=ShareStatus.ACTIVE,
                subject_id=group_id,
                display_hint="Équipe A",
            )
        )
        await session.commit()
        collections = CollectionRepository(session)
        member_groups = await GroupRepository(session).group_ids_of("sub-1")

        assert await collections.get_accessible(collection.id, "sub-1", member_groups) is not None
        assert await collections.get_accessible(collection.id, "sub-2", []) is None
        await session.execute(delete(Collection))
        await session.commit()
