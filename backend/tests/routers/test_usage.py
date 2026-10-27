from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.execution_metric import ExecutionMetric
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
        await session.execute(delete(ExecutionMetric))
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


# --- Execution metrics: time, CPU and memory of the worker tasks ---


async def _record(client, **metric) -> None:
    body = {"kind": "task", "step": "summarize_document", "duration_seconds": 10.0, "cpu_seconds": 4.0, **metric}
    response = await client.post("/api/internal/execution-metrics", headers={"X-API-Key": API_KEY}, json=body)
    assert response.status_code == 204


async def test_a_task_for_a_collection_counts_for_its_owner_with_an_estimated_energy(client):
    collection_id = (await client.post("/api/collections")).json()["id"]

    await _record(client, collection_id=collection_id, peak_rss_bytes=2_000_000_000)

    execution = (await client.get("/api/usage/me")).json()["execution"]
    assert execution["totals"]["count"] == 1
    assert execution["totals"]["duration_seconds"] == 10.0
    assert execution["totals"]["cpu_seconds"] == 4.0
    assert execution["totals"]["peak_rss_bytes"] == 2_000_000_000
    # (4 s x 10 W + 2 GB x 10 s x 0.375 W/GB) / 3600 x 1.2 PUE
    assert execution["totals"]["energy_wh"] == pytest.approx((40 + 7.5) / 3600 * 1.2)
    assert [(row["kind"], row["step"]) for row in execution["by_step"]] == [("task", "summarize_document")]
    assert execution["assumptions"] == {"watts_per_core": 10.0, "watts_per_gb": 0.375, "pue": 1.2}
    assert execution["by_user"] == []


async def test_the_nodes_of_a_task_are_listed_by_step_but_never_added_to_its_totals(client):
    collection_id = (await client.post("/api/collections")).json()["id"]

    await _record(client, collection_id=collection_id, step="run_agent", duration_seconds=8.0, cpu_seconds=3.0)
    await _record(
        client, collection_id=collection_id, kind="node", step="analyze_query", duration_seconds=2.0, cpu_seconds=1.0
    )

    execution = (await client.get("/api/usage/me")).json()["execution"]
    assert execution["totals"]["count"] == 1
    assert execution["totals"]["duration_seconds"] == 8.0
    assert execution["totals"]["cpu_seconds"] == 3.0
    assert sorted((row["kind"], row["step"]) for row in execution["by_step"]) == [
        ("node", "analyze_query"),
        ("task", "run_agent"),
    ]
    assert len(execution["by_day"]) == 1
    assert execution["by_day"][0]["count"] == 1


async def test_a_task_nobody_owns_is_not_in_anyones_report(client):
    await _record(client)

    execution = (await client.get("/api/usage/me")).json()["execution"]
    assert execution["totals"]["count"] == 0


async def test_an_invalid_metric_is_refused(client):
    response = await client.post(
        "/api/internal/execution-metrics",
        headers={"X-API-Key": API_KEY},
        json={"kind": "thread", "step": "x", "duration_seconds": 1, "cpu_seconds": 1},
    )
    assert response.status_code == 422
