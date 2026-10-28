"""The charts the agent draws (#434): stored by the backend, served only to the owner of the conversation."""

import base64
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import storage
from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.chart import Chart
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.run import Run, RunStatus

API_KEY = "test-worker-key"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
def bucket(monkeypatch) -> dict[str, bytes]:
    """The objects of RustFS (no storage is involved), and what was deleted from it."""
    objects: dict[str, bytes] = {}
    monkeypatch.setattr(storage, "put_object", lambda key, data, content_type="": objects.__setitem__(key, data))
    monkeypatch.setattr(storage, "get_object", lambda key: (objects[key], "image/png"))
    monkeypatch.setattr(storage, "delete_objects", lambda keys: [objects.pop(key, None) for key in keys])
    return objects


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.commit()


def _as(user_id: str):
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@x.fr", roles=["user"], is_admin=False
    )


async def _run(owner: str = "dev-user", status: RunStatus = RunStatus.RUNNING) -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=owner, title="Test")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Chart it")
        session.add(message)
        await session.flush()
        run = Run(
            user_id=owner, message_id=message.id, conversation_id=conversation.id, query="Chart it", status=status
        )
        session.add(run)
        await session.commit()
        return conversation.id, run.id


def _body(png: bytes = PNG, **extra) -> dict:
    return {
        "spec": {"type": "bar", "x": "region", "y": ["total"], "title": "Total"},
        "title": "Total par région",
        "width": 900,
        "height": 540,
        "png_base64": base64.b64encode(png).decode(),
        **extra,
    }


async def _create(client, run_id, **kwargs):
    return await client.post(
        f"/api/internal/runs/{run_id}/charts", json=_body(**kwargs), headers={"X-API-Key": API_KEY}
    )


async def test_a_chart_is_stored_and_its_markdown_given_back(client, bucket):
    conversation_id, run_id = await _run()

    response = await _create(client, run_id)

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == f"/api/conversations/{conversation_id}/charts/{body['id']}.png"
    assert body["markdown"] == f"![Total par région]({body['url']})"
    assert bucket == {f"charts/{conversation_id}/{body['id']}.png": PNG}
    async with async_session_factory() as session:
        chart = (await session.scalars(select(Chart))).one()
        assert chart.run_id == run_id and chart.message_id is None and chart.status == "ready"


async def test_the_title_cannot_close_the_alternative_text(client, bucket):
    _, run_id = await _run()

    response = await _create(client, run_id, title="a](https://evil.example/x) [b\nc")

    markdown = response.json()["markdown"]
    assert markdown.startswith("![a](https://evil.example/x) b c](/api/conversations/") is False
    assert "](https://evil" not in markdown.split("](/api/")[0] and markdown.count("](") == 1


async def test_only_a_png_of_a_fit_size_is_taken(client, bucket):
    _, run_id = await _run()

    assert (await _create(client, run_id, png=b"<svg onload=alert(1)>")).status_code == 422
    assert (await _create(client, run_id, png=PNG + b"0" * (2 * 1024 * 1024))).status_code == 422
    assert (await _create(client, run_id, png_base64="not base64 !!")).status_code == 422
    assert bucket == {}


async def test_a_run_that_is_not_running_takes_no_chart(client, bucket):
    _, run_id = await _run(status=RunStatus.COMPLETED)

    assert (await _create(client, run_id)).status_code == 409
    assert (await _create(client, uuid.uuid4())).status_code == 404


async def test_six_charts_at_most_per_answer(client, bucket):
    _, run_id = await _run()

    codes = [(await _create(client, run_id)).status_code for _ in range(7)]

    assert codes == [201] * 6 + [409]


async def test_the_owner_reads_the_image_and_nobody_else(client, bucket):
    conversation_id, run_id = await _run(owner="alice")
    created = (await _create(client, run_id)).json()
    url = created["url"]

    _as("alice")
    mine = await client.get(url)
    _as("mallory")
    theirs = await client.get(url)

    assert mine.status_code == 200 and mine.content == PNG and mine.headers["content-type"] == "image/png"
    assert "private" in mine.headers["cache-control"] and mine.headers["x-content-type-options"] == "nosniff"
    assert theirs.status_code == 404


async def test_a_chart_is_not_served_under_another_conversation(client, bucket):
    _, run_id = await _run(owner="alice")
    other_conversation, _ = await _run(owner="alice")
    created = (await _create(client, run_id)).json()

    _as("alice")
    response = await client.get(f"/api/conversations/{other_conversation}/charts/{created['id']}.png")

    assert response.status_code == 404


async def test_the_charts_of_a_run_belong_to_its_message_once_it_is_made(client, bucket):
    conversation_id, run_id = await _run()
    await _create(client, run_id)

    response = await client.patch(
        f"/api/internal/runs/{run_id}/result",
        json={"answer": "Voilà", "citations": [], "grounding_valid": True},
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    async with async_session_factory() as session:
        chart = (await session.scalars(select(Chart))).one()
        message = await session.get(Message, chart.message_id)
        assert message is not None and message.role == MessageRole.ASSISTANT and message.content == "Voilà"


async def test_the_charts_go_with_the_conversation_and_so_do_their_images(client, bucket):
    conversation_id, run_id = await _run(owner="alice")
    created = (await _create(client, run_id)).json()
    assert len(bucket) == 1

    _as("alice")
    response = await client.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 204
    assert bucket == {}
    async with async_session_factory() as session:
        assert (await session.scalars(select(Chart).where(Chart.id == uuid.UUID(created["id"])))).all() == []
