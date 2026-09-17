import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.app_settings import AppSettings


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        settings = await session.get(AppSettings, 1)
        if settings is not None:
            await session.delete(settings)
            await session.commit()


def _as_user(user_id: str, email: str, *, is_admin: bool):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id, email=email, roles=["admin"] if is_admin else ["user"], is_admin=is_admin
        )

    return override


async def test_get_settings_requires_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com", is_admin=False)
    response = await client.get("/api/admin/settings")
    assert response.status_code == 403


async def test_get_settings_defaults_to_none(client):
    response = await client.get("/api/admin/settings")
    assert response.status_code == 200
    assert response.json() == {"embedding_model": None}


async def test_update_embedding_model_requires_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com", is_admin=False)
    response = await client.patch("/api/admin/settings/embedding-model", json={"embedding_model": "text-embedding-3"})
    assert response.status_code == 403


async def test_update_embedding_model_persists(client):
    response = await client.patch(
        "/api/admin/settings/embedding-model", json={"embedding_model": "text-embedding-3-large"}
    )
    assert response.status_code == 200
    assert response.json() == {"embedding_model": "text-embedding-3-large"}

    follow_up = await client.get("/api/admin/settings")
    assert follow_up.json() == {"embedding_model": "text-embedding-3-large"}
