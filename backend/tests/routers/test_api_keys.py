"""The personal API keys (#521, #513): making, listing and revoking them, and what a key stands for."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.api_key import ApiKey
from app.models.group import Group, GroupMember
from app.services import api_key_service
from app.services.api_key_service import (
    ApiKeyRateLimitedError,
    ApiKeyService,
    InvalidApiKeyError,
)


@pytest.fixture(autouse=True)
def _peppers(monkeypatch):
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v1=test-pepper"))


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = _as_user("alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(ApiKey))
        await session.execute(delete(Group))
        await session.commit()


def _as_user(user_id: str, groups: list[str] | None = None):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False, groups=groups or []
        )

    return override


async def _create(client, name: str = "Mon script", scopes: list[str] | None = None, **extra) -> dict:
    response = await client.post("/api/api-keys", json={"name": name, "scopes": scopes or ["search"], **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def _authenticate(key: str, scope: str = "search") -> RequestContext:
    async with async_session_factory() as db:
        return await ApiKeyService(db).authenticate(key, scope)


# --- making a key ---


async def test_a_key_is_shown_once_when_it_is_made_and_never_again(client):
    created = await _create(client)

    assert created["key"].startswith("sk-muffin-")
    assert created["key_prefix"] == created["key"][:16]
    assert created["scopes"] == ["search"]
    assert created["revoked_at"] is None and created["last_used_at"] is None
    listed = (await client.get("/api/api-keys")).json()
    assert [item["id"] for item in listed] == [created["id"]]
    assert "key" not in listed[0]
    assert created["key"] not in str(listed)


async def test_the_answer_that_carries_a_key_is_not_to_be_stored_by_anything(client):
    response = await client.post("/api/api-keys", json={"name": "k", "scopes": ["search"]})

    assert response.headers["cache-control"] == "no-store"


async def test_only_the_hash_of_a_key_is_stored(client):
    created = await _create(client)

    async with async_session_factory() as session:
        row = (await session.execute(select(ApiKey))).scalar_one()
    assert row.key_hash.startswith("v1$") and len(row.key_hash) == 3 + 64
    every_value = " ".join(str(value) for value in vars(row).values())
    assert created["key"] not in every_value
    assert created["key"][16:] not in every_value


async def test_a_key_expires_after_ninety_days_unless_asked_otherwise(client):
    created = await _create(client)
    expires = datetime.fromisoformat(created["expires_at"])

    assert timedelta(days=89) < expires - datetime.now(UTC) < timedelta(days=91)
    short = await _create(client, name="court", expires_in_days=7)
    assert timedelta(days=6) < datetime.fromisoformat(short["expires_at"]) - datetime.now(UTC) < timedelta(days=8)


async def test_a_key_cannot_last_longer_than_the_most_allowed(client):
    response = await client.post("/api/api-keys", json={"name": "k", "scopes": ["search"], "expires_in_days": 4000})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"name": "k", "scopes": []},
        {"name": "k", "scopes": ["admin"]},
        {"name": "", "scopes": ["search"]},
        {"name": "k", "scopes": ["search"], "expires_in_days": 0},
    ],
)
async def test_a_key_that_cannot_be_is_refused(client, body):
    assert (await client.post("/api/api-keys", json=body)).status_code == 422


async def test_keys_are_off_when_no_pepper_is_set(client, monkeypatch):
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr(""))

    response = await client.post("/api/api-keys", json={"name": "k", "scopes": ["search"]})

    assert response.status_code == 503


async def test_a_user_cannot_have_more_keys_than_the_limit_but_revoked_ones_do_not_count(client, monkeypatch):
    monkeypatch.setattr(api_key_service._settings, "API_KEYS_PER_USER", 2)
    first = await _create(client, name="un")
    await _create(client, name="deux")

    assert (await client.post("/api/api-keys", json={"name": "trois", "scopes": ["search"]})).status_code == 409
    assert (await client.delete(f"/api/api-keys/{first['id']}")).status_code == 204
    await _create(client, name="trois")


# --- listing and revoking ---


async def test_a_user_only_sees_and_revokes_their_own_keys(client):
    mine = await _create(client)
    app.dependency_overrides[get_current_user] = _as_user("mallory")

    assert (await client.get("/api/api-keys")).json() == []
    assert (await client.delete(f"/api/api-keys/{mine['id']}")).status_code == 404
    app.dependency_overrides[get_current_user] = _as_user("alice")
    assert (await _authenticate(mine["key"])).user_id == "alice"


async def test_revoking_a_key_is_immediate_and_the_key_stays_listed_as_revoked(client):
    created = await _create(client)
    assert (await _authenticate(created["key"])).user_id == "alice"

    assert (await client.delete(f"/api/api-keys/{created['id']}")).status_code == 204

    with pytest.raises(InvalidApiKeyError):
        await _authenticate(created["key"])
    [listed] = (await client.get("/api/api-keys")).json()
    assert listed["revoked_at"] is not None
    # Revoking again is not an error.
    assert (await client.delete(f"/api/api-keys/{created['id']}")).status_code == 204


async def test_a_key_that_does_not_exist_cannot_be_revoked(client):
    assert (await client.delete(f"/api/api-keys/{uuid.uuid4()}")).status_code == 404


# --- what a key stands for ---


async def test_a_key_stands_for_its_owner_and_is_never_an_administrator(client):
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id="alice", email="alice@example.com", roles=["admin"], is_admin=True, groups=["/rh"]
    )
    created = await _create(client)

    context = await _authenticate(created["key"])

    assert (context.user_id, context.email, context.is_admin) == ("alice", "alice@example.com", False)
    assert "/rh" in context.groups
    assert context.access_token is None


async def test_the_muffin_groups_of_the_owner_are_looked_up_at_each_call(client):
    created = await _create(client)
    assert (await _authenticate(created["key"])).groups == []
    async with async_session_factory() as session:
        group = Group(name="RH", owner_id="alice")
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, user_id="alice", status="active"))
        await session.commit()
        group_id = str(group.id)

    assert group_id in (await _authenticate(created["key"])).groups


async def test_what_a_key_knows_of_its_owner_is_refreshed_when_they_log_in(client):
    app.dependency_overrides[get_current_user] = _as_user("alice", groups=["/rh"])
    created = await _create(client)
    async with async_session_factory() as db:
        await ApiKeyService(db).refresh_owner("alice", "new@example.com", ["/finance"])

    context = await _authenticate(created["key"])

    assert context.email == "new@example.com"
    assert context.groups == ["/finance"]


# --- presenting a key ---


async def test_a_key_is_only_good_for_what_it_was_made_for(client):
    created = await _create(client, scopes=["search"])

    with pytest.raises(InvalidApiKeyError):
        await _authenticate(created["key"], scope="chat")


async def test_an_expired_key_is_not_valid(client):
    created = await _create(client)
    async with async_session_factory() as session:
        await session.execute(update(ApiKey).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        await session.commit()

    with pytest.raises(InvalidApiKeyError):
        await _authenticate(created["key"])


@pytest.mark.parametrize("token", ["", "sk-muffin-nope", "not a key"])
async def test_what_is_not_a_key_is_not_valid(client, token):
    with pytest.raises(InvalidApiKeyError):
        await _authenticate(token)


async def test_a_well_formed_key_that_was_never_made_is_not_valid(client):
    from app.core.api_keys import generate_key

    with pytest.raises(InvalidApiKeyError):
        await _authenticate(generate_key())


async def test_with_no_pepper_no_key_is_valid(client, monkeypatch):
    created = await _create(client)
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr(""))

    with pytest.raises(InvalidApiKeyError):
        await _authenticate(created["key"])


async def test_a_key_made_under_one_pepper_works_while_that_pepper_is_kept_and_not_after(client, monkeypatch):
    old = await _create(client, name="old")
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v2=new-pepper,v1=test-pepper"))
    new = await _create(client, name="new")

    assert (await _authenticate(old["key"])).user_id == "alice"
    assert (await _authenticate(new["key"])).user_id == "alice"
    async with async_session_factory() as session:
        hashes = {row.name: row.key_hash for row in (await session.execute(select(ApiKey))).scalars()}
    assert hashes["old"].startswith("v1$") and hashes["new"].startswith("v2$")

    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v2=new-pepper"))
    with pytest.raises(InvalidApiKeyError):
        await _authenticate(old["key"])
    assert (await _authenticate(new["key"])).user_id == "alice"


async def test_a_use_is_noted_but_not_written_again_within_a_minute(client):
    created = await _create(client)
    await _authenticate(created["key"])
    async with async_session_factory() as session:
        first = (await session.execute(select(ApiKey.last_used_at))).scalar_one()
    assert first is not None

    await _authenticate(created["key"])

    async with async_session_factory() as session:
        assert (await session.execute(select(ApiKey.last_used_at))).scalar_one() == first


async def test_a_key_that_asks_too_much_is_slowed_down(client, monkeypatch):
    monkeypatch.setattr(api_key_service._settings, "API_KEY_RATE_LIMIT_PER_MINUTE", 2)
    created = await _create(client)

    await _authenticate(created["key"])
    await _authenticate(created["key"])
    with pytest.raises(ApiKeyRateLimitedError):
        await _authenticate(created["key"])
