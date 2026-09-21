import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.prompt import PromptVersion


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(PromptVersion).where(PromptVersion.name == "test_prompt"))
        await session.commit()


def _as_user(user_id: str, *, is_admin: bool):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=is_admin)

    return override


async def _as_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)


async def test_list_prompts_requires_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", is_admin=False)
    response = await client.get("/api/admin/prompts")
    assert response.status_code == 403


async def test_create_and_activate_version(client):
    await _as_admin(client)

    created = await client.post("/api/admin/prompts/test_prompt/versions", json={"content": "v1 content"})
    assert created.status_code == 200
    body = created.json()
    assert body["version"] == 1
    assert body["is_active"] is False

    activated = await client.post("/api/admin/prompts/test_prompt/versions/1/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    listed = await client.get("/api/admin/prompts")
    assert listed.status_code == 200
    summary = next(p for p in listed.json() if p["name"] == "test_prompt")
    assert summary["active_version"]["version"] == 1
    assert summary["active_version"]["content"] == "v1 content"


async def test_activating_new_version_deactivates_previous(client):
    await _as_admin(client)
    await client.post("/api/admin/prompts/test_prompt/versions", json={"content": "v1"})
    await client.post("/api/admin/prompts/test_prompt/versions/1/activate")
    await client.post("/api/admin/prompts/test_prompt/versions", json={"content": "v2"})
    activated = await client.post("/api/admin/prompts/test_prompt/versions/2/activate")
    assert activated.json()["is_active"] is True

    versions = await client.get("/api/admin/prompts/test_prompt/versions")
    by_version = {v["version"]: v["is_active"] for v in versions.json()}
    assert by_version == {1: False, 2: True}


async def test_activate_missing_version_404s(client):
    await _as_admin(client)
    response = await client.post("/api/admin/prompts/test_prompt/versions/99/activate")
    assert response.status_code == 404
