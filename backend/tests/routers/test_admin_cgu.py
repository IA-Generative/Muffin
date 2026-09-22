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
        await session.execute(delete(CguAcceptance))
        await session.execute(delete(CguVersion).where(CguVersion.version > 1))
        v1 = (await session.execute(select(CguVersion).where(CguVersion.version == 1))).scalar_one_or_none()
        if v1 is not None:
            v1.is_active = True
        await session.commit()


def _as_user(user_id: str, *, is_admin: bool):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=is_admin)

    return override


async def _as_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)


async def test_list_versions_requires_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", is_admin=False)
    response = await client.get("/api/admin/cgu/versions")
    assert response.status_code == 403


async def test_list_versions_includes_the_seeded_v1(client):
    await _as_admin(client)
    response = await client.get("/api/admin/cgu/versions")
    assert response.status_code == 200
    versions = response.json()
    assert any(v["version"] == 1 and v["is_active"] for v in versions)


async def test_create_and_activate_version(client):
    await _as_admin(client)

    created = await client.post("/api/admin/cgu/versions", json={"content": "v2 content"})
    assert created.status_code == 200
    body = created.json()
    assert body["version"] == 2
    assert body["is_active"] is False

    activated = await client.post("/api/admin/cgu/versions/2/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    versions = await client.get("/api/admin/cgu/versions")
    by_version = {v["version"]: v["is_active"] for v in versions.json()}
    assert by_version[1] is False
    assert by_version[2] is True


async def test_activating_a_version_forces_re_acceptance(client):
    """§127: a user who already accepted the old active version must be asked again once a new
    one is activated - the whole point of gating on the *active* version's id, not just "has
    accepted something once"."""
    app.dependency_overrides[get_current_user] = _as_user("user-a", is_admin=False)
    await client.post("/api/cgu/accept")  # accepts v1
    assert (await client.get("/api/cgu/status")).json()["accepted"] is True

    await _as_admin(client)
    await client.post("/api/admin/cgu/versions", json={"content": "v2 content"})
    await client.post("/api/admin/cgu/versions/2/activate")

    app.dependency_overrides[get_current_user] = _as_user("user-a", is_admin=False)
    status_response = await client.get("/api/cgu/status")
    assert status_response.json()["accepted"] is False
    assert status_response.json()["is_update"] is True


async def test_activate_missing_version_404s(client):
    await _as_admin(client)
    response = await client.post("/api/admin/cgu/versions/99/activate")
    assert response.status_code == 404
