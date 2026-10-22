from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import worker_auth
from app.main import app
from app.routers import internal_openai_compat
from app.schemas.internal_pipeline import LlmUsageContext

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client


def _headers(key: str = API_KEY) -> dict[str, str]:
    # The OpenAI wire format: Bearer, not X-API-Key - what promptfoo's judge sends.
    return {"Authorization": f"Bearer {key}"}


def _fake_openai_client() -> SimpleNamespace:
    async def create_chat(model: str, **kwargs):
        return SimpleNamespace(
            id="chatcmpl-123",
            created=1700000000,
            model=model,
            choices=[
                SimpleNamespace(
                    index=0,
                    message=SimpleNamespace(role="assistant", content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=create_chat))))


async def test_chat_completions_requires_bearer_key(client):
    response = await client.post(
        "/api/internal/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401


async def test_chat_completions_rejects_wrong_bearer_key(client):
    response = await client.post(
        "/api/internal/v1/chat/completions",
        headers=_headers("wrong-key"),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401


async def test_chat_completions_returns_503_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(internal_openai_compat, "_openai_client", None)
    response = await client.post(
        "/api/internal/v1/chat/completions",
        headers=_headers(),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 503


async def test_chat_completions_returns_openai_wire_format(client, monkeypatch):
    fake_client = _fake_openai_client()
    monkeypatch.setattr(internal_openai_compat, "_openai_client", fake_client)
    record = AsyncMock()
    monkeypatch.setattr(internal_openai_compat, "UsageService", lambda db: SimpleNamespace(record=record))

    response = await client.post(
        "/api/internal/v1/chat/completions",
        headers=_headers(),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "temperature": 0},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    # Only the parameters the caller set are forwarded - an explicit None would mean
    # something else to the OpenAI SDK than an omitted one.
    fake_client.chat.completions.create.assert_awaited_once_with(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0,
    )


async def test_chat_completions_records_usage_for_the_collection(client, monkeypatch):
    fake_client = _fake_openai_client()
    record = AsyncMock()
    monkeypatch.setattr(internal_openai_compat, "_openai_client", fake_client)
    monkeypatch.setattr(internal_openai_compat, "UsageService", lambda db: SimpleNamespace(record=record))

    response = await client.post(
        "/api/internal/v1/chat/completions",
        headers={**_headers(), "X-Collection-Id": "11111111-1111-1111-1111-111111111111"},
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    context = record.await_args[0][0]
    assert context == LlmUsageContext(step="evaluation", collection_id="11111111-1111-1111-1111-111111111111")
    assert record.await_args[0][1:] == ("chat", "gpt-4o", 10, 5)


async def test_chat_completions_without_collection_id_records_unattributed(client, monkeypatch):
    fake_client = _fake_openai_client()
    record = AsyncMock()
    monkeypatch.setattr(internal_openai_compat, "_openai_client", fake_client)
    monkeypatch.setattr(internal_openai_compat, "UsageService", lambda db: SimpleNamespace(record=record))

    response = await client.post(
        "/api/internal/v1/chat/completions",
        headers=_headers(),
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    record.assert_awaited_once()
    assert record.await_args[0][0] is None
