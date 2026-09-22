import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.cgu import CguAcceptance, CguVersion


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        # Never delete the v1 seed itself - only whatever a test created on top of it, and
        # restore it as active in case a test activated something else (§ test isolation, other
        # test files assume an active CGU version exists).
        await session.execute(delete(CguAcceptance))
        await session.execute(delete(CguVersion).where(CguVersion.version > 1))
        v1 = (await session.execute(select(CguVersion).where(CguVersion.version == 1))).scalar_one_or_none()
        if v1 is not None:
            v1.is_active = True
        await session.commit()


def _as_user(user_id: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=False)

    return override


async def test_status_not_accepted_and_not_an_update_for_a_brand_new_user(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    response = await client.get("/api/cgu/status")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["accepted"] is False
    assert body["is_update"] is False
    assert body["content"]


async def test_accept_then_status_reports_accepted(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    accept_response = await client.post("/api/cgu/accept")
    assert accept_response.status_code == 200
    assert accept_response.json()["accepted"] is True

    status_response = await client.get("/api/cgu/status")
    assert status_response.json()["accepted"] is True
    assert status_response.json()["is_update"] is False


async def test_accept_is_idempotent(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    first = await client.post("/api/cgu/accept")
    second = await client.post("/api/cgu/accept")
    assert first.status_code == 200
    assert second.status_code == 200


async def test_status_is_an_update_once_a_newer_version_is_active(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")
    await client.post("/api/cgu/accept")  # accepts v1

    async with async_session_factory() as session:
        session.add(CguVersion(version=2, content="v2 content", is_active=False))
        await session.commit()
        v1 = (await session.execute(select(CguVersion).where(CguVersion.version == 1))).scalar_one()
        v2 = (await session.execute(select(CguVersion).where(CguVersion.version == 2))).scalar_one()
        v1.is_active = False
        v2.is_active = True
        await session.commit()

    response = await client.get("/api/cgu/status")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["accepted"] is False
    assert body["is_update"] is True  # had accepted v1 before - this is a re-acceptance, not day one
