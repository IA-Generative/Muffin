import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message, MessageRole
from app.models.run import Run

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _create_run(user_id: str = "dev-user") -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="Test")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="What is the policy?")
        session.add(message)
        await session.flush()
        run = Run(
            user_id=user_id,
            message_id=message.id,
            conversation_id=conversation.id,
            query="What is the policy?",
        )
        session.add(run)
        await session.commit()
        return run.id


async def test_get_run(client):
    run_id = await _create_run()
    response = await client.get(f"/api/internal/runs/{run_id}", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "What is the policy?"
    assert body["status"] == "queued"


async def test_get_run_not_found(client):
    response = await client.get(f"/api/internal/runs/{uuid.uuid4()}", headers=_headers())
    assert response.status_code == 404


async def test_update_run_status(client):
    run_id = await _create_run()
    response = await client.patch(
        f"/api/internal/runs/{run_id}/status",
        headers=_headers(),
        json={"status": "running", "current_node": "query_analysis", "current_activity": "Analyzing the query"},
    )
    assert response.status_code == 200

    body = (await client.get(f"/api/internal/runs/{run_id}", headers=_headers())).json()
    assert body["status"] == "running"


async def test_update_run_state_merges_not_replaces(client):
    run_id = await _create_run()
    await client.patch(
        f"/api/internal/runs/{run_id}/state",
        headers=_headers(),
        json={"research_plan": {"tasks": ["a"]}, "plan_version": 1},
    )
    response = await client.patch(
        f"/api/internal/runs/{run_id}/state", headers=_headers(), json={"budget": {"max_tasks": 5}}
    )
    assert response.status_code == 200

    body = (await client.get(f"/api/internal/runs/{run_id}", headers=_headers())).json()
    assert body["research_plan"] == {"tasks": ["a"]}
    assert body["budget"] == {"max_tasks": 5}
    assert body["plan_version"] == 1


async def test_update_run_result(client):
    run_id = await _create_run()
    response = await client.patch(
        f"/api/internal/runs/{run_id}/result",
        headers=_headers(),
        json={"answer": "Telework is allowed 2 days/week.", "citations": [{"source_id": "doc-1"}]},
    )
    assert response.status_code == 200

    body = (await client.get(f"/api/internal/runs/{run_id}", headers=_headers())).json()
    assert body["answer"] == "Telework is allowed 2 days/week."
    assert body["citations"] == [{"source_id": "doc-1"}]


async def test_update_run_error(client):
    run_id = await _create_run()
    response = await client.patch(
        f"/api/internal/runs/{run_id}/error", headers=_headers(), json={"error": "LLM hub unavailable"}
    )
    assert response.status_code == 200


async def test_create_run_event(client):
    run_id = await _create_run()
    response = await client.post(
        f"/api/internal/runs/{run_id}/events",
        headers=_headers(),
        json={"type": "run_started", "data": {"query": "hi"}},
    )
    assert response.status_code == 201

    from sqlalchemy import select

    from app.db import async_session_factory as factory
    from app.models.run import RunEvent

    async with factory() as session:
        events = (await session.execute(select(RunEvent).where(RunEvent.run_id == run_id))).scalars().all()
    assert len(events) == 1
    assert events[0].type == "run_started"


async def test_create_run_event_not_found(client):
    response = await client.post(
        f"/api/internal/runs/{uuid.uuid4()}/events", headers=_headers(), json={"type": "run_started"}
    )
    assert response.status_code == 404


async def test_list_accessible_collections_owner_only(client):
    async with async_session_factory() as session:
        owned = Collection(owner_id="dev-user", name="Mine", description="")
        owned.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        other = Collection(owner_id="someone-else", name="Not mine", description="")
        other.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add_all([owned, other])
        await session.commit()

    response = await client.get("/api/internal/users/dev-user/accessible-collections", headers=_headers())

    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["Mine"]


async def test_search_finds_matching_chunk(client):
    from app.models.chunk import Chunk

    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="policy.pdf", type="file", storage_key="k")
        session.add(document)
        await session.flush()
        session.add(
            Chunk(
                document_id=document.id,
                index=0,
                text="Le télétravail est autorisé deux jours par semaine.",
                token_count=10,
            )
        )
        session.add(
            Chunk(document_id=document.id, index=1, text="Les congés payés sont de 25 jours par an.", token_count=10)
        )
        await session.commit()
        collection_id = collection.id

    response = await client.post(
        "/api/internal/search",
        headers=_headers(),
        json={"collection_ids": [str(collection_id)], "query": "télétravail", "limit": 5},
    )

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert "télétravail" in results[0]["text"]
