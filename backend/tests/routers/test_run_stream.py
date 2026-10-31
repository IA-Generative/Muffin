import asyncio
import json
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.connectors import async_redis
from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.run import Run, RunStatus
from app.routers import runs as runs_router
from app.services import run_stream

WORKER_API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_API_KEY)


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = _as_user("alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    runs_router._open_streams.clear()
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.commit()
    redis = async_redis()
    async for key in redis.scan_iter("run:*:stream"):
        await redis.delete(key)


def _as_user(user_id: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False)

    return override


async def _create_run(client) -> str:
    with patch("app.services.run_service.agent_runner.start"):
        response = await client.post("/api/runs", json={"query": "What is the telework policy?"})
    return response.json()["id"]


async def _set_status(run_id: str, status: RunStatus) -> None:
    async with async_session_factory() as session:
        await session.execute(update(Run).where(Run.id == uuid.UUID(run_id)).values(status=status))
        await session.commit()


def _events(body: str) -> list[dict]:
    """The server-sent events of a response: {"id", "event", "data"} for each, comments and `retry` left out."""
    out = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            out.append({"id": fields.get("id"), "event": fields["event"], "data": json.loads(fields["data"])})
    return out


async def test_a_finished_run_is_replayed_in_order_and_the_stream_ends_on_its_last_status(client):
    run_id = await _create_run(client)
    await run_stream.publish(run_id, run_stream.STEP, {"id": "e1", "type": "run_started"})
    await run_stream.publish(run_id, run_stream.DELTA, {"text": "Le télé", "replace": False})
    await run_stream.publish(run_id, run_stream.DELTA, {"text": "travail", "replace": False})
    await run_stream.publish(run_id, run_stream.STATUS, {"status": "completed"})
    await _set_status(run_id, RunStatus.COMPLETED)

    response = await client.get(f"/api/runs/{run_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    events = _events(response.text)
    assert [event["event"] for event in events] == ["step", "delta", "delta", "status"]
    assert [event["data"].get("text") for event in events[1:3]] == ["Le télé", "travail"]
    assert events[-1]["data"] == {"status": "completed"}


async def test_the_stream_resumes_after_the_last_event_the_client_got(client):
    run_id = await _create_run(client)
    for text in ("un ", "deux ", "trois"):
        await run_stream.publish(run_id, run_stream.DELTA, {"text": text, "replace": False})
    await run_stream.publish(run_id, run_stream.STATUS, {"status": "completed"})
    await _set_status(run_id, RunStatus.COMPLETED)
    first = _events((await client.get(f"/api/runs/{run_id}/stream")).text)

    resumed = _events((await client.get(f"/api/runs/{run_id}/stream", headers={"Last-Event-ID": first[1]["id"]})).text)

    assert [event["data"].get("text") for event in resumed[:1]] == ["trois"]
    assert resumed[-1]["event"] == "status"


async def test_a_run_over_whose_stream_has_expired_ends_with_its_status_from_the_database(client):
    run_id = await _create_run(client)
    await _set_status(run_id, RunStatus.FAILED)

    events = _events((await client.get(f"/api/runs/{run_id}/stream")).text)

    assert events == [{"id": None, "event": "status", "data": {"status": "failed"}}]


async def test_a_run_that_ends_without_a_word_in_the_stream_is_ended_by_the_database(client, monkeypatch):
    """A pod that went down says nothing: the sweeper marks the run failed, and the stream must not wait forever."""
    monkeypatch.setattr(runs_router._run_settings, "RUN_STREAM_PING_SECONDS", 1)
    run_id = await _create_run(client)
    await run_stream.publish(run_id, run_stream.STEP, {"id": "e1", "type": "run_started"})
    await _set_status(run_id, RunStatus.RUNNING)

    async def fail_soon():
        await asyncio.sleep(0.3)
        await _set_status(run_id, RunStatus.FAILED)

    task = asyncio.create_task(fail_soon())
    events = _events((await client.get(f"/api/runs/{run_id}/stream")).text)
    await task

    assert events[0]["event"] == "step"
    assert events[-1] == {"id": None, "event": "status", "data": {"status": "failed"}}


async def test_the_run_of_another_user_cannot_be_followed(client):
    run_id = await _create_run(client)
    app.dependency_overrides[get_current_user] = _as_user("mallory")

    response = await client.get(f"/api/runs/{run_id}/stream")

    assert response.status_code == 404


async def test_a_run_that_does_not_exist_is_a_404(client):
    assert (await client.get(f"/api/runs/{uuid.uuid4()}/stream")).status_code == 404


async def test_a_user_cannot_hold_more_streams_open_than_the_limit(client, monkeypatch):
    run_id = await _create_run(client)
    monkeypatch.setattr(runs_router._run_settings, "RUN_STREAMS_PER_USER", 2)
    runs_router._open_streams["alice"] = 2

    assert (await client.get(f"/api/runs/{run_id}/stream")).status_code == 429
    # Another user is not held back by it.
    runs_router._open_streams["alice"] = 0


async def test_a_stream_that_cannot_be_read_says_so_and_ends(client):
    run_id = await _create_run(client)

    with patch("app.services.run_stream.read", side_effect=RuntimeError("redis down")):
        events = _events((await client.get(f"/api/runs/{run_id}/stream")).text)

    assert events == [{"id": None, "event": "unavailable", "data": {}}]


async def test_the_count_of_open_streams_is_given_back_when_a_stream_ends(client):
    run_id = await _create_run(client)
    await run_stream.publish(run_id, run_stream.STATUS, {"status": "completed"})
    await _set_status(run_id, RunStatus.COMPLETED)

    await client.get(f"/api/runs/{run_id}/stream")

    assert runs_router._open_streams["alice"] == 0


async def test_publishing_never_fails_when_redis_does(monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(run_stream, "async_redis", broken)

    await run_stream.publish(str(uuid.uuid4()), run_stream.DELTA, {"text": "x"})  # must not raise


async def test_a_step_reported_by_the_agent_reaches_the_stream(client):
    run_id = await _create_run(client)

    response = await client.post(
        f"/api/internal/runs/{run_id}/events",
        headers={"X-API-Key": WORKER_API_KEY},
        json={"type": "vdb_discovery_started", "data": {"count": 3}, "task_id": None},
    )

    assert response.status_code == 201
    [entry] = await run_stream.read(run_id, "0-0", 0)
    assert entry.kind == run_stream.STEP
    assert entry.payload["type"] == "vdb_discovery_started"
    assert entry.payload["data"] == {"count": 3}
    assert entry.payload["created_at"]
    # The id is the event's own: what the chat gets from the stream and from GET /runs/{id}/events is the same event.
    events = (await client.get(f"/api/runs/{run_id}/events")).json()
    assert entry.payload["id"] == events[0]["id"]


async def test_a_status_reported_by_the_agent_reaches_the_stream(client):
    run_id = await _create_run(client)

    await client.patch(
        f"/api/internal/runs/{run_id}/status",
        headers={"X-API-Key": WORKER_API_KEY},
        json={"status": "completed", "current_node": None, "current_activity": None},
    )

    [entry] = await run_stream.read(run_id, "0-0", 0)
    assert entry.kind == run_stream.STATUS
    assert entry.payload["status"] == "completed"
