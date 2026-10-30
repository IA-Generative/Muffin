"""A share that lets write (#454): who may change a collection besides its owner."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import get_current_user
from app.core.sharing import hash_identifier, normalize_email, normalize_group
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.repositories.collection_repository import CollectionRepository
from app.services.collection_service import CollectionNotEditableError, CollectionNotFoundError
from app.services.editing_rights import require_editable_collection
from tests.routers.test_collections import _as_user


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


async def _owner_creates_and_shares_with_julie(client, permission: str | None, parent_id: str | None = None):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    body = {"subject_type": "user", "identifier": "julie@example.com"}
    if permission:
        body["permission"] = permission
    share = await client.post(f"/api/collections/{created['id']}/shares", json=body)
    async with async_session_factory() as session:
        await CollectionRepository(session).resolve_pending_user_shares(
            hash_identifier(normalize_email("julie@example.com")), "julie-sub"
        )
        await session.commit()
    return created, share


async def _can_edit(collection_id: str, user_id: str, groups: list[str] | None = None, is_admin: bool = False) -> bool:
    from app.core.security.factory import RequestContext

    user = RequestContext(user_id=user_id, email="", roles=[], is_admin=is_admin, groups=groups or [])
    async with async_session_factory() as session:
        try:
            await require_editable_collection(CollectionRepository(session), user, collection_id)
        except CollectionNotEditableError:
            return False
        except CollectionNotFoundError:
            return False
        return True


async def test_a_share_reads_unless_it_is_asked_to_write(client):
    _, share = await _owner_creates_and_shares_with_julie(client, None)

    assert share.status_code == 201
    assert share.json()["permission"] == "read"


async def test_the_owner_chooses_read_or_write_when_sharing(client):
    _, share = await _owner_creates_and_shares_with_julie(client, "write")

    assert share.json()["permission"] == "write"


async def test_a_reader_sees_the_collection_but_may_not_change_it(client):
    created, _ = await _owner_creates_and_shares_with_julie(client, "read")

    app.dependency_overrides[get_current_user] = _as_user("julie-sub", "julie@example.com")
    detail = (await client.get(f"/api/collections/{created['id']}")).json()

    assert (detail["is_owner"], detail["can_edit"]) == (False, False)
    assert await _can_edit(created["id"], "julie-sub") is False


async def test_a_writer_may_change_the_collection_but_does_not_own_it(client):
    created, _ = await _owner_creates_and_shares_with_julie(client, "write")

    app.dependency_overrides[get_current_user] = _as_user("julie-sub", "julie@example.com")
    detail = (await client.get(f"/api/collections/{created['id']}")).json()

    assert (detail["is_owner"], detail["can_edit"]) == (False, True)
    assert await _can_edit(created["id"], "julie-sub") is True
    # Settings, sharing and deletion stay with the owner.
    assert (await client.get(f"/api/collections/{created['id']}/shares")).status_code == 404
    assert (await client.delete(f"/api/collections/{created['id']}")).status_code == 404


async def test_the_owner_changes_a_share_from_read_to_write_and_back(client):
    created, share = await _owner_creates_and_shares_with_julie(client, "read")
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    url = f"/api/collections/{created['id']}/shares/{share.json()['id']}"

    assert (await client.patch(url, json={"permission": "write"})).json()["permission"] == "write"
    assert await _can_edit(created["id"], "julie-sub") is True
    assert (await client.patch(url, json={"permission": "read"})).json()["permission"] == "read"
    assert await _can_edit(created["id"], "julie-sub") is False


async def test_only_the_owner_changes_a_share(client):
    created, share = await _owner_creates_and_shares_with_julie(client, "read")
    app.dependency_overrides[get_current_user] = _as_user("julie-sub", "julie@example.com")

    response = await client.patch(
        f"/api/collections/{created['id']}/shares/{share.json()['id']}", json={"permission": "write"}
    )

    assert response.status_code == 404


async def test_a_group_share_that_writes_reaches_the_members_of_the_group(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    await client.post(
        f"/api/collections/{created['id']}/shares",
        json={"subject_type": "group", "identifier": "/muffin-dev-team", "permission": "write"},
    )
    async with async_session_factory() as session:
        await CollectionRepository(session).resolve_pending_group_shares(
            hash_identifier(normalize_group("/muffin-dev-team")), "/muffin-dev-team"
        )
        await session.commit()

    assert await _can_edit(created["id"], "member", groups=["/muffin-dev-team"]) is True
    assert await _can_edit(created["id"], "outsider", groups=["/other"]) is False


async def test_write_is_inherited_down_the_tree_like_read(client):
    parent, _ = await _owner_creates_and_shares_with_julie(client, "write")
    child = (await client.post("/api/collections", json={"parent_id": parent["id"]})).json()

    assert await _can_edit(child["id"], "julie-sub") is True


async def test_a_public_collection_does_not_let_write(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    await client.patch(f"/api/collections/{created['id']}/visibility", json={"visibility": "public"})

    assert await _can_edit(created["id"], "anyone") is False


async def test_an_administrator_may_change_what_they_can_see_not_what_they_cannot(client):
    created, _ = await _owner_creates_and_shares_with_julie(client, "read")

    assert await _can_edit(created["id"], "julie-sub", is_admin=True) is True
    assert await _can_edit(created["id"], "stranger", is_admin=True) is False
