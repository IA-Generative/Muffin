from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.token_usage import TokenUsage, UserProfile
from app.routers import internal_llm
from tests.routers.test_collections import _as_user
from tests.routers.test_internal_llm import API_KEY, _fake_openai_client


@pytest.fixture(autouse=True)
def _llm(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
    fake_client = _fake_openai_client(["gpt-4o", "embedder"], chat_capable_ids={"gpt-4o"})

    async def create_embedding(model: str, **_kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1])], usage=SimpleNamespace(prompt_tokens=7))

    fake_client.embeddings.create.side_effect = create_embedding
    monkeypatch.setattr(internal_llm, "_openai_client", fake_client)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(TokenUsage))
        await session.execute(delete(UserProfile))
        await session.execute(delete(Collection))
        await session.commit()
    app.dependency_overrides.pop(get_current_user, None)


async def _chat(client, usage: dict | None = None) -> None:
    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    if usage is not None:
        body["usage"] = usage
    response = await client.post("/api/internal/llm/chat", headers={"X-API-Key": API_KEY}, json=body)
    assert response.status_code == 200


async def test_a_call_for_a_collection_counts_for_its_owner(client):
    collection_id = (await client.post("/api/collections")).json()["id"]

    await _chat(client, {"step": "summarize_document", "collection_id": collection_id})

    mine = (await client.get("/api/usage/me")).json()
    assert mine["totals"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "calls": 1}
    assert [(row["step"], row["total_tokens"]) for row in mine["by_step"]] == [("summarize_document", 15)]
    assert [(row["model"], row["calls"]) for row in mine["by_model"]] == [("gpt-4o", 1)]
    assert len(mine["by_day"]) == 1
    assert mine["by_user"] == []


async def test_embeddings_are_counted_as_input_tokens(client):
    response = await client.post(
        "/api/internal/llm/embed",
        headers={"X-API-Key": API_KEY},
        json={"model": "embedder", "input": "hello", "usage": {"step": "embed_chunks", "user_id": "dev-user"}},
    )
    assert response.status_code == 200

    totals = (await client.get("/api/usage/me")).json()["totals"]
    assert totals == {"input_tokens": 7, "output_tokens": 0, "total_tokens": 7, "calls": 1}


async def test_someone_else_s_consumption_is_not_in_mine(client):
    await _chat(client, {"step": "generate_answer", "user_id": "someone-else"})
    await _chat(client)

    assert (await client.get("/api/usage/me")).json()["totals"]["calls"] == 0


async def test_admin_sees_everyone_and_can_focus_on_one_user(client):
    await client.get("/api/auth/me")  # records dev-user's display name
    await _chat(client, {"step": "generate_answer", "user_id": "dev-user"})
    await _chat(client, {"step": "generate_answer", "user_id": "someone-else"})
    await _chat(client)

    overall = (await client.get("/api/admin/usage")).json()
    assert overall["totals"]["calls"] == 3
    users = {row["user_id"]: row["display"] for row in overall["by_user"]}
    assert users == {"dev-user": "dev@example.com", "someone-else": None, None: None}

    focused = (await client.get("/api/admin/usage", params={"user_id": "someone-else"})).json()
    assert focused["totals"]["calls"] == 1
    # The per-user list stays complete so the admin can switch to someone else.
    assert len(focused["by_user"]) == 3


async def test_admin_usage_is_admin_only(client):
    app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")
    assert (await client.get("/api/admin/usage")).status_code == 403
    assert (await client.get("/api/usage/me")).status_code == 200
