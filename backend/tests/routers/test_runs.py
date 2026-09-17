import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.run import Run


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.commit()


def _as_user(user_id: str, email: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False)

    return override


async def _create_run(client, query: str = "What is the telework policy?"):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        response = await client.post("/api/runs", json={"query": query})
    return response


async def test_create_run_creates_conversation_message_and_run(client):
    response = await _create_run(client)

    assert response.status_code == 202
    body = response.json()
    assert body["query"] == "What is the telework policy?"
    assert body["status"] == "queued"
    assert body["cancel_requested"] is False
    assert body["answer"] is None

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(body["id"]))
    assert run is not None
    assert run.celery_task_id == "celery-run-1"
    assert run.message_id is not None
    assert run.conversation_id is not None


async def test_create_run_reuses_an_existing_conversation(client):
    first = (await _create_run(client)).json()
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-2"):
        second = await client.post(
            "/api/runs", json={"query": "And what about leave policy?", "conversation_id": first["conversation_id"]}
        )

    assert second.status_code == 202
    assert second.json()["conversation_id"] == first["conversation_id"]
    # But each run still gets its own message.
    assert second.json()["id"] != first["id"]


async def test_create_run_for_unknown_conversation_returns_404(client):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-3"):
        response = await client.post("/api/runs", json={"query": "hello", "conversation_id": str(uuid.uuid4())})
    assert response.status_code == 404


async def test_get_run_not_found(client):
    response = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_runs_are_scoped_to_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    created = (await _create_run(client)).json()

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.get(f"/api/runs/{created['id']}")
    assert response.status_code == 404


async def test_list_run_events_empty_initially(client):
    created = (await _create_run(client)).json()
    response = await client.get(f"/api/runs/{created['id']}/events")
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_cancel_run_sets_cancel_requested_and_revokes(client):
    created = (await _create_run(client)).json()

    with patch("app.services.run_service.revoke_task") as mock_revoke:
        response = await client.post(f"/api/runs/{created['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["cancel_requested"] is True
    mock_revoke.assert_called_once_with("celery-run-1")


async def test_cancel_unknown_run_returns_404(client):
    response = await client.post(f"/api/runs/{uuid.uuid4()}/cancel")
    assert response.status_code == 404
