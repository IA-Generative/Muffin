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


async def _create_report(client, title="Idée de fonctionnalité") -> dict:
    app.dependency_overrides[get_current_user] = _as_user("reporter")
    response = await client.post(
        "/api/reports",
        data={"type": "idea", "title": title, "description": "Ce serait bien d'avoir X"},
    )
    assert response.status_code == 201
    return response.json()


async def test_list_reports_forbidden_for_non_admin(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a")

    response = await client.get("/api/admin/reports")

    assert response.status_code == 403


async def test_list_reports_as_admin(client):
    created = await _create_report(client)

    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)
    response = await client.get("/api/admin/reports")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == created["id"]
    assert body[0]["user_display"]  # resolved at creation, never the raw sub


async def test_list_reports_filters_by_status(client):
    await _create_report(client)

    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)
    response = await client.get("/api/admin/reports", params={"status_filter": "resolved"})

    assert response.status_code == 200
    assert response.json() == []


async def test_update_report_status_and_response(client):
    created = await _create_report(client)

    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)
    response = await client.patch(
        f"/api/admin/reports/{created['id']}",
        json={"status": "resolved", "admin_response": "Merci, corrigé dans la prochaine version."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["admin_response"] == "Merci, corrigé dans la prochaine version."
    assert body["responded_by"]


async def test_update_report_status_without_response_keeps_previous_response(client):
    created = await _create_report(client)
    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)
    await client.patch(
        f"/api/admin/reports/{created['id']}", json={"status": "in_progress", "admin_response": "On regarde."}
    )

    response = await client.patch(f"/api/admin/reports/{created['id']}", json={"status": "resolved"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["admin_response"] == "On regarde."


async def test_update_report_forbidden_for_non_admin(client):
    created = await _create_report(client)

    app.dependency_overrides[get_current_user] = _as_user("user-a")
    response = await client.patch(f"/api/admin/reports/{created['id']}", json={"status": "resolved"})

    assert response.status_code == 403


async def test_update_report_not_found(client):
    app.dependency_overrides[get_current_user] = _as_user("admin-a", is_admin=True)

    response = await client.patch(
        "/api/admin/reports/00000000-0000-0000-0000-000000000000", json={"status": "resolved"}
    )

    assert response.status_code == 404
