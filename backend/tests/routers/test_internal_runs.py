import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.conversation import Conversation
from app.models.document import Document, DocumentPage
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
        await session.flush()
        session.add(Document(collection_id=owned.id, name="a.pdf", type="file", storage_key="a"))
        session.add(Document(collection_id=owned.id, name="b.pdf", type="file", storage_key="b"))
        await session.commit()

    response = await client.get("/api/internal/users/dev-user/accessible-collections", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body] == ["Mine"]
    assert body[0]["document_count"] == 2


async def test_list_collection_documents_requires_ownership(client):
    async with async_session_factory() as session:
        collection = Collection(owner_id="someone-else", name="Not mine", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.commit()
        collection_id = collection.id

    response = await client.get(
        f"/api/internal/users/dev-user/collections/{collection_id}/documents", headers=_headers()
    )

    assert response.status_code == 404


async def test_list_collection_documents_returns_name_status_and_summary(client):
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        session.add(
            Document(
                collection_id=collection.id,
                name="handbook.pdf",
                type="file",
                storage_key="k",
                summary="Employee handbook.",
            )
        )
        await session.commit()
        collection_id = collection.id

    response = await client.get(
        f"/api/internal/users/dev-user/collections/{collection_id}/documents", headers=_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "handbook.pdf"
    assert body[0]["summary"] == "Employee handbook."


async def test_get_document_page_requires_ownership(client):
    async with async_session_factory() as session:
        collection = Collection(owner_id="someone-else", name="Not mine", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="doc.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        document_id = document.id

    response = await client.get(f"/api/internal/users/dev-user/documents/{document_id}/pages/1", headers=_headers())

    assert response.status_code == 404


async def test_get_document_page_returns_content_and_screenshot_url(client, monkeypatch):
    from app.routers import internal_runs

    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="doc.pdf", type="file", storage_key="k")
        session.add(document)
        await session.flush()
        session.add(
            DocumentPage(document_id=document.id, page_number=1, content="Page one text.", screenshot="shots/p1.png")
        )
        await session.commit()
        document_id = document.id

    monkeypatch.setattr(internal_runs.storage, "get_presigned_url", lambda key: f"https://example.com/{key}")

    response = await client.get(f"/api/internal/users/dev-user/documents/{document_id}/pages/1", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "Page one text."
    assert body["screenshot_url"] == "https://example.com/shots/p1.png"


async def test_search_finds_matching_chunk(client, monkeypatch):
    from types import SimpleNamespace

    from app.models.chunk import Chunk
    from app.services import search_service, vector_store

    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="policy.pdf", type="file", storage_key="k")
        session.add(document)
        await session.flush()
        telework_chunk = Chunk(
            document_id=document.id,
            index=0,
            text="Le télétravail est autorisé deux jours par semaine.",
            token_count=10,
        )
        session.add(telework_chunk)
        session.add(
            Chunk(document_id=document.id, index=1, text="Les congés payés sont de 25 jours par an.", token_count=10)
        )
        await session.commit()
        collection_id = collection.id
        telework_chunk_id = telework_chunk.id

    # The vector store itself (Qdrant) isn't exercised here - only that the search endpoint
    # embeds the query, asks vector_store.search per selected collection, and hydrates whatever
    # chunk ids come back. Qdrant ranking behavior is covered by app/services/vector_store.py
    # being a thin pass-through to the qdrant-client SDK, not worth re-testing against a fake.
    async def create_embedding(**_kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])

    fake_openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=create_embedding))
    monkeypatch.setattr(search_service, "_openai_client", fake_openai_client)
    monkeypatch.setattr(
        vector_store, "search", lambda collection_id, query_embedding, limit: [(telework_chunk_id, 0.9)]
    )

    response = await client.post(
        "/api/internal/search",
        headers=_headers(),
        json={"collection_ids": [str(collection_id)], "query": "télétravail", "limit": 5},
    )

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert "télétravail" in results[0]["text"]
    assert results[0]["chunk_id"] == str(telework_chunk_id)


async def test_search_tolerates_an_embedding_model_that_is_unavailable(client, monkeypatch):
    """A collection's embedding_model can be misconfigured/unavailable on the LLM hub (real
    incident: the hub didn't have "text-embedding-3-small") - that must degrade to empty results
    for that collection, never a 500 that fails the whole request for every other collection."""
    from types import SimpleNamespace

    from app.services import search_service

    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="not-a-real-model")
        session.add(collection)
        await session.commit()
        collection_id = collection.id

    async def failing_embedding(**_kwargs):
        raise RuntimeError("model 'not-a-real-model' not found")

    fake_openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=failing_embedding))
    monkeypatch.setattr(search_service, "_openai_client", fake_openai_client)

    response = await client.post(
        "/api/internal/search",
        headers=_headers(),
        json={"collection_ids": [str(collection_id)], "query": "télétravail", "limit": 5},
    )

    assert response.status_code == 200
    assert response.json() == []
