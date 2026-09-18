import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import get_current_user
from app.core.sharing import hash_identifier, normalize_email, normalize_group
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.repositories.collection_repository import CollectionRepository
from tests.routers.test_collections import _as_user


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


async def test_collection_is_private_by_default(client):
    created = (await client.post("/api/collections")).json()
    assert created["visibility"] == "private"
    assert created["is_owner"] is True


async def test_owner_can_make_a_collection_public(client):
    created = (await client.post("/api/collections")).json()

    response = await client.patch(f"/api/collections/{created['id']}/visibility", json={"visibility": "public"})

    assert response.status_code == 200
    assert response.json()["visibility"] == "public"


async def test_public_collection_is_visible_read_only_to_a_non_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    await client.patch(f"/api/collections/{created['id']}/visibility", json={"visibility": "public"})

    app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")
    listed = (await client.get("/api/collections")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["is_owner"] is False

    detail = await client.get(f"/api/collections/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["is_owner"] is False

    # Read-only: a non-owner (even on a public collection) can't manage its sharing.
    assert (await client.get(f"/api/collections/{created['id']}/shares")).status_code == 404
    assert (
        await client.patch(f"/api/collections/{created['id']}/visibility", json={"visibility": "private"})
    ).status_code == 404


async def test_private_collection_is_invisible_to_a_non_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()

    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")
    assert (await client.get("/api/collections")).json()["total"] == 0
    assert (await client.get(f"/api/collections/{created['id']}")).status_code == 404


async def test_create_share_never_reveals_the_email_and_masks_it_for_display(client):
    created = (await client.post("/api/collections")).json()

    response = await client.post(
        f"/api/collections/{created['id']}/shares", json={"subject_type": "user", "identifier": "Julie@Example.com"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert "julie@example.com" not in str(body)
    assert body["display_hint"] == "j***@e***.c***"


async def test_inviting_the_same_email_twice_is_rejected(client):
    created = (await client.post("/api/collections")).json()
    payload = {"subject_type": "user", "identifier": "julie@example.com"}

    first = await client.post(f"/api/collections/{created['id']}/shares", json=payload)
    second = await client.post(f"/api/collections/{created['id']}/shares", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


async def test_list_and_revoke_shares(client):
    created = (await client.post("/api/collections")).json()
    share = (
        await client.post(
            f"/api/collections/{created['id']}/shares", json={"subject_type": "user", "identifier": "julie@example.com"}
        )
    ).json()

    listed = (await client.get(f"/api/collections/{created['id']}/shares")).json()
    assert len(listed) == 1
    assert listed[0]["id"] == share["id"]

    revoke = await client.delete(f"/api/collections/{created['id']}/shares/{share['id']}")
    assert revoke.status_code == 204
    assert (await client.get(f"/api/collections/{created['id']}/shares")).json() == []


async def test_revoking_an_unknown_share_returns_404(client):
    created = (await client.post("/api/collections")).json()

    response = await client.delete(f"/api/collections/{created['id']}/shares/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


async def test_shares_are_owner_only(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()

    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")
    response = await client.post(
        f"/api/collections/{created['id']}/shares", json={"subject_type": "user", "identifier": "julie@example.com"}
    )
    assert response.status_code == 404


async def test_user_share_resolves_to_active_when_the_invited_email_logs_in(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    await client.post(
        f"/api/collections/{created['id']}/shares", json={"subject_type": "user", "identifier": "julie@example.com"}
    )

    # Passive resolution at login - never something the owner or anyone else can trigger/observe
    # directly, see app/core/sharing.py. Exercised at the repository layer used by
    # app/routers/auth.py::_resolve_pending_shares, not through a mocked Keycloak round-trip.
    async with async_session_factory() as session:
        repository = CollectionRepository(session)
        await repository.resolve_pending_user_shares(hash_identifier(normalize_email("julie@example.com")), "julie-sub")
        await session.commit()

    app.dependency_overrides[get_current_user] = _as_user("julie-sub", "julie@example.com")
    listed = (await client.get("/api/collections")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == created["id"]

    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    shares = (await client.get(f"/api/collections/{created['id']}/shares")).json()
    assert shares[0]["status"] == "active"


async def test_group_share_resolves_to_active_for_a_member_of_that_group(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    await client.post(
        f"/api/collections/{created['id']}/shares",
        json={"subject_type": "group", "identifier": "/muffin-dev-team"},
    )

    async with async_session_factory() as session:
        repository = CollectionRepository(session)
        await repository.resolve_pending_group_shares(
            hash_identifier(normalize_group("/muffin-dev-team")), "/muffin-dev-team"
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = _as_user(
        "team-member", "member@example.com", groups=["/muffin-dev-team"]
    )
    listed = (await client.get("/api/collections")).json()
    assert listed["total"] == 1


async def test_group_share_does_not_grant_access_to_a_non_member(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    created = (await client.post("/api/collections")).json()
    await client.post(
        f"/api/collections/{created['id']}/shares",
        json={"subject_type": "group", "identifier": "/muffin-dev-team"},
    )

    async with async_session_factory() as session:
        repository = CollectionRepository(session)
        await repository.resolve_pending_group_shares(
            hash_identifier(normalize_group("/muffin-dev-team")), "/muffin-dev-team"
        )
        await session.commit()

    app.dependency_overrides[get_current_user] = _as_user("outsider", "outsider@example.com", groups=["/other-team"])
    listed = (await client.get("/api/collections")).json()
    assert listed["total"] == 0


async def test_create_share_is_unavailable_without_a_configured_pepper(client, monkeypatch):
    from app.core import sharing

    monkeypatch.setattr(sharing._sharing_settings, "SHARE_INVITE_PEPPER", "")
    created = (await client.post("/api/collections")).json()

    response = await client.post(
        f"/api/collections/{created['id']}/shares", json={"subject_type": "user", "identifier": "julie@example.com"}
    )

    assert response.status_code == 503
