import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


async def _create_collection_and_document() -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(
            embedding_model="text-embedding-3-small",
            instructions_summary="Be concise.",
            generation_models={"summary": "gpt-4o"},
            pipeline_windows={"summary_pages_per_map": 3},
        )
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="report.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def test_get_collection_settings_merges_saved_and_default_windows(client):
    collection_id, _ = await _create_collection_and_document()

    response = await client.get(f"/api/internal/collections/{collection_id}/settings", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["instructions"]["summary"] == "Be concise."
    assert body["generation_models"]["summary"] == "gpt-4o"
    # Saved key is present, but this endpoint returns the raw stored dict -
    # the worker itself merges in PIPELINE_WINDOW_DEFAULTS for missing keys.
    assert body["pipeline_windows"]["summary_pages_per_map"] == 3


async def test_get_collection_settings_not_found(client):
    response = await client.get(f"/api/internal/collections/{uuid.uuid4()}/settings", headers=_headers())
    assert response.status_code == 404


async def test_create_qa_pair(client):
    collection_id, document_id = await _create_collection_and_document()

    response = await client.post(
        f"/api/internal/collections/{collection_id}/qa-pairs",
        headers=_headers(),
        json={"document_id": str(document_id), "question": "What is this?", "answer": "A report."},
    )

    assert response.status_code == 201
    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.qa import QaPair

        pairs = (await session.execute(select(QaPair).where(QaPair.collection_id == collection_id))).scalars().all()
    assert len(pairs) == 1
    assert pairs[0].question == "What is this?"
    assert pairs[0].origin == "generated"


async def test_upsert_entity_creates_then_bumps_mentions(client):
    collection_id, document_id = await _create_collection_and_document()

    first = await client.post(
        f"/api/internal/collections/{collection_id}/entities",
        headers=_headers(),
        json={"document_id": str(document_id), "name": "Acme Corp", "type": "organisation", "mentions_delta": 1},
    )
    assert first.status_code == 200
    assert first.json()["mentions"] == 1

    second = await client.post(
        f"/api/internal/collections/{collection_id}/entities",
        headers=_headers(),
        json={"document_id": str(document_id), "name": "Acme Corp", "type": "organisation", "mentions_delta": 2},
    )
    assert second.status_code == 200
    assert second.json()["mentions"] == 3
    assert second.json()["id"] == first.json()["id"]


async def test_create_relation_between_two_entities(client):
    collection_id, document_id = await _create_collection_and_document()

    entity_a = (
        await client.post(
            f"/api/internal/collections/{collection_id}/entities",
            headers=_headers(),
            json={"document_id": str(document_id), "name": "Alice", "type": "personne"},
        )
    ).json()
    entity_b = (
        await client.post(
            f"/api/internal/collections/{collection_id}/entities",
            headers=_headers(),
            json={"document_id": str(document_id), "name": "Acme Corp", "type": "organisation"},
        )
    ).json()

    response = await client.post(
        f"/api/internal/collections/{collection_id}/relations",
        headers=_headers(),
        json={
            "document_id": str(document_id),
            "from_entity_id": entity_a["id"],
            "to_entity_id": entity_b["id"],
            "type": "works_at",
        },
    )
    assert response.status_code == 201

    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.entity import Relation

        relations = (
            (await session.execute(select(Relation).where(Relation.collection_id == collection_id))).scalars().all()
        )
    assert len(relations) == 1
    assert relations[0].type == "works_at"


async def test_get_collection_metadata_includes_description_tags_and_document_summaries(client):
    collection_id, document_id = await _create_collection_and_document()
    async with async_session_factory() as session:
        from sqlalchemy import select

        from app.models.collection import Collection as CollectionModel
        from app.models.document import Document as DocumentModel

        collection = (
            await session.execute(select(CollectionModel).where(CollectionModel.id == collection_id))
        ).scalar_one()
        collection.description = "An existing description."
        document = (await session.execute(select(DocumentModel).where(DocumentModel.id == document_id))).scalar_one()
        document.summary = "This document is about widgets."
        await session.commit()

    response = await client.get(f"/api/internal/collections/{collection_id}/metadata", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "An existing description."
    assert body["tags"] == []
    assert body["document_summaries"] == ["This document is about widgets."]


async def test_get_collection_metadata_not_found(client):
    response = await client.get(f"/api/internal/collections/{uuid.uuid4()}/metadata", headers=_headers())
    assert response.status_code == 404


async def test_update_collection_description(client):
    collection_id, _ = await _create_collection_and_document()

    response = await client.patch(
        f"/api/internal/collections/{collection_id}/description",
        headers=_headers(),
        json={"description": "A collection about widgets."},
    )
    assert response.status_code == 200

    metadata = (await client.get(f"/api/internal/collections/{collection_id}/metadata", headers=_headers())).json()
    assert metadata["description"] == "A collection about widgets."


async def test_update_collection_tags(client):
    collection_id, _ = await _create_collection_and_document()

    response = await client.put(
        f"/api/internal/collections/{collection_id}/tags", headers=_headers(), json={"tags": ["widgets", "reports"]}
    )
    assert response.status_code == 200

    metadata = (await client.get(f"/api/internal/collections/{collection_id}/metadata", headers=_headers())).json()
    assert sorted(metadata["tags"]) == ["reports", "widgets"]


async def test_update_collection_description_embedding_creates_then_replaces(client):
    collection_id, _ = await _create_collection_and_document()

    first = await client.patch(
        f"/api/internal/collections/{collection_id}/description-embedding",
        headers=_headers(),
        json={"model": "text-embedding-3-small", "embedding": [0.1, 0.2, 0.3]},
    )
    assert first.status_code == 200

    second = await client.patch(
        f"/api/internal/collections/{collection_id}/description-embedding",
        headers=_headers(),
        json={"model": "text-embedding-3-large", "embedding": [0.4, 0.5, 0.6]},
    )
    assert second.status_code == 200

    async with async_session_factory() as session:
        from app.models.collection import CollectionDescriptionEmbedding

        row = await session.get(CollectionDescriptionEmbedding, collection_id)
    assert row is not None
    assert row.model == "text-embedding-3-large"
    assert row.embedding == [0.4, 0.5, 0.6]


async def test_update_collection_description_embedding_not_found(client):
    response = await client.patch(
        f"/api/internal/collections/{uuid.uuid4()}/description-embedding",
        headers=_headers(),
        json={"model": "text-embedding-3-small", "embedding": [0.1]},
    )
    assert response.status_code == 404


async def test_update_collection_description_embedding_indexes_in_meilisearch(client, monkeypatch):
    from app.services import vector_store

    collection_id, _ = await _create_collection_and_document()
    await client.patch(
        f"/api/internal/collections/{collection_id}/description",
        headers=_headers(),
        json={"description": "A collection about widgets."},
    )
    await client.put(f"/api/internal/collections/{collection_id}/tags", headers=_headers(), json={"tags": ["widgets"]})

    calls = []
    monkeypatch.setattr(
        vector_store,
        "upsert_collection_description",
        lambda collection_id, description, tags, embedding: calls.append((collection_id, description, tags, embedding)),
    )

    response = await client.patch(
        f"/api/internal/collections/{collection_id}/description-embedding",
        headers=_headers(),
        json={"model": "text-embedding-3-small", "embedding": [0.1, 0.2]},
    )

    assert response.status_code == 200
    assert calls == [(collection_id, "A collection about widgets.", ["widgets"], [0.1, 0.2])]


async def test_update_collection_description_embedding_indexing_failure_does_not_fail_the_request(client, monkeypatch):
    """Best-effort indexing (§124) - the Postgres embedding is already committed by the time
    Meilisearch is touched, so a Meilisearch failure here must not roll back a successful write
    or surface as an error to the worker."""
    from app.services import vector_store

    collection_id, _ = await _create_collection_and_document()

    def _raise(*args, **kwargs):
        raise RuntimeError("Meilisearch unreachable")

    monkeypatch.setattr(vector_store, "upsert_collection_description", _raise)

    response = await client.patch(
        f"/api/internal/collections/{collection_id}/description-embedding",
        headers=_headers(),
        json={"model": "text-embedding-3-small", "embedding": [0.1]},
    )

    assert response.status_code == 200


async def test_update_collection_tags_indexes_tags_in_meilisearch(client, monkeypatch):
    from app.services import vector_store

    collection_id, _ = await _create_collection_and_document()

    calls = []
    monkeypatch.setattr(
        vector_store, "update_collection_tags_in_index", lambda collection_id, tags: calls.append((collection_id, tags))
    )

    response = await client.put(
        f"/api/internal/collections/{collection_id}/tags", headers=_headers(), json={"tags": ["widgets", "reports"]}
    )

    assert response.status_code == 200
    assert calls == [(collection_id, ["widgets", "reports"])]


async def test_search_collections_finds_matching_collection(client, monkeypatch):
    from types import SimpleNamespace

    from app.models.app_settings import AppSettings
    from app.services import search_service, vector_store

    collection_id, _ = await _create_collection_and_document()
    async with async_session_factory() as session:
        session.add(AppSettings(id=1, embedding_model="text-embedding-3-small"))
        await session.commit()

    async def create_embedding(**_kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])

    fake_openai_client = SimpleNamespace(embeddings=SimpleNamespace(create=create_embedding))
    monkeypatch.setattr(search_service, "_openai_client", fake_openai_client)
    monkeypatch.setattr(
        vector_store,
        "search_collections",
        lambda query, query_embedding, collection_ids, limit: [(collection_id, 0.87)],
    )

    response = await client.post(
        "/api/internal/collections/search",
        headers=_headers(),
        json={"collection_ids": [str(collection_id)], "query": "widgets", "limit": 5},
    )

    assert response.status_code == 200
    results = response.json()
    assert results == [{"collection_id": str(collection_id), "score": 0.87}]


async def test_search_collections_no_llm_hub_configured_returns_empty(client):
    """No real LLM hub configured in tests (search_service._openai_client is None, same as
    every other search endpoint's OPENAI_API_KEY-less-test-env default) - fails open to no
    suggestions, never a 500."""
    collection_id, _ = await _create_collection_and_document()

    response = await client.post(
        "/api/internal/collections/search",
        headers=_headers(),
        json={"collection_ids": [str(collection_id)], "query": "widgets", "limit": 5},
    )

    assert response.status_code == 200
    assert response.json() == []
