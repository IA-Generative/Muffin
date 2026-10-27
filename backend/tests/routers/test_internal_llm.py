import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.app_settings import AppSettings
from app.routers import internal_llm

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        settings = await session.get(AppSettings, 1)
        if settings is not None:
            await session.delete(settings)
            await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def _fake_openai_client(
    all_ids: list[str],
    chat_capable_ids: set[str] = frozenset(),
    embedding_capable_ids: set[str] = frozenset(),
) -> SimpleNamespace:
    async def create_chat(model: str, **_kwargs):
        if model not in chat_capable_ids:
            raise RuntimeError(f"model '{model}' does not support chat completions")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    async def create_embedding(model: str, **_kwargs):
        if model not in embedding_capable_ids:
            raise RuntimeError(f"model '{model}' does not support embeddings")
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

    models_data = [SimpleNamespace(id=i) for i in all_ids]
    return SimpleNamespace(
        models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=models_data))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create_chat))),
        embeddings=SimpleNamespace(create=AsyncMock(side_effect=create_embedding)),
    )


async def test_chat_requires_api_key(client):
    response = await client.post("/api/internal/llm/chat", json={"model": "gpt-4o", "messages": []})
    assert response.status_code == 401


async def test_chat_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(internal_llm, "_openai_client", None)
    response = await client.post(
        "/api/internal/llm/chat",
        headers=_headers(),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 503


async def test_chat_returns_completion_content(client, monkeypatch):
    fake_client = _fake_openai_client(["gpt-4o"], chat_capable_ids={"gpt-4o"})
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)

    response = await client.post(
        "/api/internal/llm/chat",
        headers=_headers(),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "content": "ok",
        "prompt_tokens": 10,
        "completion_tokens": 5,
    }


async def test_default_chat_model_probes_until_the_first_supported_model(client, monkeypatch):
    # The default path only ever wants the first model: it probes in order and stops at the
    # first success, rather than sweeping every model at once (which trips the hub's rate
    # limiter). It never writes the full-list cache - that is the UI's /models route's job.
    fake_client = _fake_openai_client(["a-embed", "b-chat", "c-chat"], chat_capable_ids={"b-chat", "c-chat"})
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)

    with patch("app.routers.internal_llm.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = None
        response = await client.get("/api/internal/llm/default-chat-model", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"model": "b-chat"}
    # a-embed (not chat-capable) then b-chat: two probes, and c-chat is never reached.
    assert fake_client.chat.completions.create.await_count == 2
    mock_redis.client.set.assert_not_called()


async def test_default_chat_model_uses_cache(client, monkeypatch):
    fake_client = _fake_openai_client([], chat_capable_ids=set())
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)

    with patch("app.routers.internal_llm.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = json.dumps(["cached-model"])
        response = await client.get("/api/internal/llm/default-chat-model", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"model": "cached-model"}
    fake_client.models.list.assert_not_called()


async def test_default_chat_model_returns_none_when_no_model_supports_chat(client, monkeypatch):
    fake_client = _fake_openai_client(["gpt-4o"], chat_capable_ids=set())
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)

    with patch("app.routers.internal_llm.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = None
        response = await client.get("/api/internal/llm/default-chat-model", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"model": None}
    mock_redis.client.set.assert_not_called()


async def test_default_chat_model_returns_none_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(internal_llm, "_openai_client", None)
    response = await client.get("/api/internal/llm/default-chat-model", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"model": None}


async def test_embed_returns_vector(client, monkeypatch):
    fake_client = _fake_openai_client(["text-embedding-3-small"], embedding_capable_ids={"text-embedding-3-small"})
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)

    response = await client.post(
        "/api/internal/llm/embed",
        headers=_headers(),
        json={"model": "text-embedding-3-small", "input": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {"embedding": [0.1, 0.2, 0.3]}


async def test_default_embedding_model_prefers_admin_setting(client, monkeypatch):
    fake_client = _fake_openai_client(["text-embedding-3-small"], embedding_capable_ids={"text-embedding-3-small"})
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)
    async with async_session_factory() as session:
        session.add(AppSettings(id=1, embedding_model="admin-chosen-model"))
        await session.commit()

    response = await client.get("/api/internal/llm/default-embedding-model", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"model": "admin-chosen-model"}
    fake_client.models.list.assert_not_called()


async def test_default_embedding_model_falls_back_to_hub_discovery(client, monkeypatch):
    fake_client = _fake_openai_client(
        ["gpt-4o", "text-embedding-3-small"],
        embedding_capable_ids={"text-embedding-3-small"},
    )
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)

    with patch("app.routers.internal_llm.redis_connector") as mock_redis:
        mock_redis.client.get.return_value = None
        response = await client.get("/api/internal/llm/default-embedding-model", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"model": "text-embedding-3-small"}


def _fake_streaming_client(pieces: list[str]) -> SimpleNamespace:
    async def create_chat(**kwargs):
        assert kwargs["stream"] is True

        async def chunks():
            for piece in pieces:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece))], usage=None)
            # The last chunk of a stream asked with include_usage: no choice, only the usage.
            yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))

        return chunks()

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create_chat))))


async def test_chat_stream_sends_the_text_as_it_is_written_then_the_usage(client, monkeypatch):
    monkeypatch.setattr(internal_llm, "_openai_client", _fake_streaming_client(["Hel", "lo"]))

    response = await client.post(
        "/api/internal/llm/chat-stream",
        headers=_headers(),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert [json.loads(line) for line in response.text.splitlines()] == [
        {"delta": "Hel"},
        {"delta": "lo"},
        {"done": True, "prompt_tokens": 10, "completion_tokens": 5},
    ]


async def test_chat_stream_requires_api_key(client):
    response = await client.post("/api/internal/llm/chat-stream", json={"model": "gpt-4o", "messages": []})
    assert response.status_code == 401
