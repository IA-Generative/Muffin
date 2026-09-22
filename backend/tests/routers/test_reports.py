from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.report import Report


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Report))
        await session.commit()


def _as_user(user_id: str, *, is_admin: bool = False):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=is_admin)

    return override


async def _create_report(client, title="Bouton cassé", type_="bug") -> dict:
    response = await client.post(
        "/api/reports",
        data={"type": type_, "title": title, "description": "Ça ne marche pas"},
    )
    assert response.status_code == 201
    return response.json()


async def test_create_report_without_screenshot(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    body = await _create_report(client)

    assert body["type"] == "bug"
    assert body["title"] == "Bouton cassé"
    assert body["status"] == "new"
    assert body["screenshot_url"] is None
    assert body["admin_response"] is None


async def test_create_report_with_screenshot_uploads_to_storage(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    with (
        patch("app.services.report_service.storage.put_object") as mock_put,
        patch("app.services.report_service.storage.get_presigned_url", return_value="https://example.com/shot.png"),
    ):
        response = await client.post(
            "/api/reports",
            data={"type": "bug", "title": "Titre", "description": "Description"},
            files={"screenshot": ("shot.png", b"fake-png-bytes", "image/png")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["screenshot_url"] == "https://example.com/shot.png"
    mock_put.assert_called_once()


async def test_list_my_reports_only_returns_own(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")
    await _create_report(client, title="Report A")

    app.dependency_overrides[get_current_user] = _as_user("user-b")
    await _create_report(client, title="Report B")

    response = await client.get("/api/reports")

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()]
    assert titles == ["Report B"]


async def test_get_report_forbidden_for_a_different_non_admin_user(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")
    created = await _create_report(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b")
    response = await client.get(f"/api/reports/{created['id']}")

    assert response.status_code == 403


async def test_get_report_not_found(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    response = await client.get("/api/reports/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
