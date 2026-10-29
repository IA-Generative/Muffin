import pytest
from httpx import ASGITransport, AsyncClient

from app.core import tasks
from app.core.security.factory import RequestContext, get_current_user
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)


def _as(is_admin: bool) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id="u", email="u@example.test", roles=[], is_admin=is_admin
    )


async def test_an_administrator_starts_a_synchronisation(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(
        tasks._celery_app,
        "send_task",
        lambda name, queue: sent.update(name=name, queue=queue) or type("R", (), {"id": "t1"})(),
    )
    _as(True)

    response = await client.post("/api/admin/owui-sync")

    assert response.status_code == 202
    assert response.json() == {"task_id": "t1"}
    assert sent == {"name": "app.tasks.sync_owui", "queue": "owui_sync"}


async def test_anyone_else_cannot(client, monkeypatch):
    monkeypatch.setattr(tasks, "enqueue_sync_owui", lambda: pytest.fail("must not be started"))
    _as(False)

    assert (await client.post("/api/admin/owui-sync")).status_code == 403
