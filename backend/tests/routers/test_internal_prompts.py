import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.connectors import redis_connector
from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.prompt import PromptVersion, RunPromptUsage
from app.models.run import Run

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    redis_connector.client.delete("prompts:active:test_prompt")
    async with async_session_factory() as session:
        await session.execute(delete(RunPromptUsage))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(PromptVersion).where(PromptVersion.name == "test_prompt"))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _create_run(user_id: str = "dev-user") -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="Test")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="hi")
        session.add(message)
        await session.flush()
        run = Run(user_id=user_id, message_id=message.id, conversation_id=conversation.id, query="hi")
        session.add(run)
        await session.commit()
        return run.id


async def test_get_active_prompt_requires_api_key(client):
    response = await client.get("/api/internal/prompts/test_prompt/active")
    assert response.status_code == 401


async def test_get_active_prompt_404s_when_none_active(client):
    response = await client.get("/api/internal/prompts/test_prompt/active", headers=_headers())
    assert response.status_code == 404


async def test_get_active_prompt_returns_active_version(client):
    async with async_session_factory() as session:
        session.add(PromptVersion(name="test_prompt", version=1, content="hello", is_active=True))
        await session.commit()

    response = await client.get("/api/internal/prompts/test_prompt/active", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "test_prompt"
    assert body["version"] == 1
    assert body["content"] == "hello"

    # Served from cache on a second call - deactivating server-side shouldn't be visible yet.
    async with async_session_factory() as session:
        version = await session.get(PromptVersion, uuid.UUID(body["id"]))
        version.is_active = False
        await session.commit()
    cached = await client.get("/api/internal/prompts/test_prompt/active", headers=_headers())
    assert cached.status_code == 200
    assert cached.json()["content"] == "hello"


async def test_record_run_prompt_usages(client):
    run_id = await _create_run()
    async with async_session_factory() as session:
        version = PromptVersion(name="test_prompt", version=1, content="hello", is_active=True)
        session.add(version)
        await session.commit()
        version_id = version.id

    response = await client.post(
        f"/api/internal/prompts/runs/{run_id}/usages",
        json={"prompt_version_ids": [str(version_id)]},
        headers=_headers(),
    )
    assert response.status_code == 200

    async with async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(RunPromptUsage).where(RunPromptUsage.run_id == run_id))
        usages = list(result.scalars())
    assert len(usages) == 1
    assert usages[0].prompt_version_id == version_id
