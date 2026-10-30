"""The groups people make in Muffin (#455): who makes them, manages them, and what a member sees."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security.factory import RequestContext, get_current_user
from app.core.sharing import hash_identifier, normalize_email
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionShare
from app.models.group import Group, GroupMember
from app.repositories.group_repository import GroupRepository


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.execute(delete(Group))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


def _as(user_id: str, *, admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=admin
    )


async def _make(client, name="Équipe A", owner="owner") -> dict:
    _as(owner)
    response = await client.post("/api/groups", json={"name": name, "description": "Les voisins"})
    assert response.status_code == 201
    return response.json()


async def test_anyone_makes_a_group_and_owns_it(client):
    group = await _make(client)

    assert (group["name"], group["is_owner"], group["can_manage"], group["source"]) == (
        "Équipe A",
        True,
        True,
        "muffin",
    )
    assert group["member_count"] == 0
    listed = (await client.get("/api/groups")).json()
    assert [item["id"] for item in listed] == [group["id"]]


async def test_a_group_is_invisible_to_someone_who_is_not_in_it(client):
    group = await _make(client)

    _as("stranger")
    assert (await client.get("/api/groups")).json() == []
    assert (await client.get(f"/api/groups/{group['id']}")).status_code == 404


async def test_the_owner_adds_a_member_by_subject_and_they_see_the_group(client):
    group = await _make(client)
    added = await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "julie-sub"})
    assert (added.status_code, added.json()["status"]) == (201, "active")

    _as("julie-sub")
    seen = (await client.get(f"/api/groups/{group['id']}")).json()
    assert (seen["member_count"], seen["is_owner"], seen["can_manage"]) == (1, False, False)
    assert [item["id"] for item in (await client.get("/api/groups")).json()] == [group["id"]]


async def test_a_member_only_knows_how_many_they_are_and_changes_nothing(client):
    group = await _make(client)
    await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "julie-sub"})

    _as("julie-sub")
    assert (await client.get(f"/api/groups/{group['id']}/members")).status_code == 403
    assert (await client.patch(f"/api/groups/{group['id']}", json={"name": "Autre"})).status_code == 403
    assert (await client.delete(f"/api/groups/{group['id']}")).status_code == 403
    assert (await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "x"})).status_code == 403


async def test_an_email_is_an_invitation_that_never_shows_the_address(client):
    group = await _make(client)

    added = await client.post(f"/api/groups/{group['id']}/members", json={"email": "Julie@Example.com"})

    assert added.status_code == 201
    assert added.json()["status"] == "pending"
    assert "julie@example.com" not in added.text.lower()
    members = (await client.get(f"/api/groups/{group['id']}/members")).json()
    assert [(m["status"], m["display"]) for m in members] == [("pending", "j***@e***.c***")]
    assert (await client.get(f"/api/groups/{group['id']}")).json()["pending_count"] == 1


async def test_the_same_person_cannot_be_added_twice(client):
    group = await _make(client)
    url = f"/api/groups/{group['id']}/members"

    assert (await client.post(url, json={"email": "julie@example.com"})).status_code == 201
    assert (await client.post(url, json={"email": "JULIE@example.com"})).status_code == 409
    assert (await client.post(url, json={"user_id": "sub-1"})).status_code == 201
    assert (await client.post(url, json={"user_id": "sub-1"})).status_code == 409


async def test_one_way_to_say_who_to_add_not_two_or_none(client):
    group = await _make(client)
    url = f"/api/groups/{group['id']}/members"

    assert (await client.post(url, json={})).status_code == 422
    assert (await client.post(url, json={"email": "a@example.com", "user_id": "x"})).status_code == 422


async def test_an_invitation_becomes_a_member_when_the_person_signs_in(client):
    group = await _make(client)
    await client.post(f"/api/groups/{group['id']}/members", json={"email": "julie@example.com"})

    async with async_session_factory() as session:
        repository = GroupRepository(session)
        assert await repository.group_ids_of("julie-sub") == []
        await repository.resolve_pending_members(hash_identifier(normalize_email("julie@example.com")), "julie-sub")
        await session.commit()
        assert await repository.group_ids_of("julie-sub") == [group["id"]]

    members = (await client.get(f"/api/groups/{group['id']}/members")).json()
    assert [m["status"] for m in members] == ["active"]


async def test_an_invitation_to_a_group_someone_is_already_in_is_dropped_when_they_sign_in(client):
    group = await _make(client)
    await client.post(f"/api/groups/{group['id']}/members", json={"email": "julie@example.com"})
    await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "julie-sub"})

    async with async_session_factory() as session:
        await GroupRepository(session).resolve_pending_members(
            hash_identifier(normalize_email("julie@example.com")), "julie-sub"
        )
        await session.commit()

    assert [m["status"] for m in (await client.get(f"/api/groups/{group['id']}/members")).json()] == ["active"]


async def test_removing_a_member_takes_the_group_away_from_them(client):
    group = await _make(client)
    member = (await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "julie-sub"})).json()

    assert (await client.delete(f"/api/groups/{group['id']}/members/{member['id']}")).status_code == 204
    async with async_session_factory() as session:
        assert await GroupRepository(session).group_ids_of("julie-sub") == []
    assert (await client.delete(f"/api/groups/{group['id']}/members/{member['id']}")).status_code == 404


async def test_the_owner_renames_a_group(client):
    group = await _make(client)

    renamed = await client.patch(f"/api/groups/{group['id']}", json={"name": "Équipe B"})

    assert (renamed.status_code, renamed.json()["name"], renamed.json()["description"]) == (
        200,
        "Équipe B",
        "Les voisins",
    )


async def test_deleting_a_group_takes_its_members_and_the_shares_that_pointed_to_it(client):
    group = await _make(client)
    await client.post(f"/api/groups/{group['id']}/members", json={"user_id": "julie-sub"})
    async with async_session_factory() as session:
        collection = Collection(owner_id="owner", name="c")
        session.add(collection)
        await session.flush()
        session.add(
            CollectionShare(
                collection_id=collection.id,
                subject_type="group",
                status="active",
                subject_id=group["id"],
                display_hint="Équipe A",
            )
        )
        await session.commit()

    assert (await client.delete(f"/api/groups/{group['id']}")).status_code == 204

    async with async_session_factory() as session:
        assert (await session.scalars(select(GroupMember))).all() == []
        assert (await session.scalars(select(CollectionShare))).all() == []
        assert await GroupRepository(session).group_ids_of("julie-sub") == []


async def test_an_administrator_sees_and_manages_every_group(client):
    group = await _make(client)

    _as("admin", admin=True)
    assert [item["id"] for item in (await client.get("/api/groups")).json()] == [group["id"]]
    assert (await client.patch(f"/api/groups/{group['id']}", json={"name": "Admin"})).status_code == 200
    assert (await client.delete(f"/api/groups/{group['id']}")).status_code == 204


async def test_a_group_copied_from_open_webui_is_read_only_for_everyone(client):
    async with async_session_factory() as session:
        copied = await GroupRepository(session).sync_external("owui", "g1", "Copiée", "", ["julie-sub"])
        await session.commit()
        group_id = str(copied.group.id)

    _as("julie-sub")
    seen = (await client.get(f"/api/groups/{group_id}")).json()
    assert (seen["source"], seen["can_manage"], seen["member_count"]) == ("owui", False, 1)

    _as("admin", admin=True)
    assert (await client.patch(f"/api/groups/{group_id}", json={"name": "x"})).status_code == 409
    assert (await client.delete(f"/api/groups/{group_id}")).status_code == 409
    assert (await client.post(f"/api/groups/{group_id}/members", json={"user_id": "x"})).status_code == 409


async def test_signing_in_turns_the_invitations_to_groups_into_members(client):
    from app.routers.auth import _resolve_pending_shares

    group = await _make(client)
    await client.post(f"/api/groups/{group['id']}/members", json={"email": "julie@example.com"})

    async with async_session_factory() as session:
        await _resolve_pending_shares(session, {"user_id": "julie-sub", "email": "Julie@Example.com", "groups": []})

    _as("julie-sub")
    assert [item["id"] for item in (await client.get("/api/groups")).json()] == [group["id"]]
