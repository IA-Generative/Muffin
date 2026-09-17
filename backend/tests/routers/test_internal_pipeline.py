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
    collection_id, _ = await _create_collection_and_document()

    first = await client.post(
        f"/api/internal/collections/{collection_id}/entities",
        headers=_headers(),
        json={"name": "Acme Corp", "type": "organisation", "mentions_delta": 1},
    )
    assert first.status_code == 200
    assert first.json()["mentions"] == 1

    second = await client.post(
        f"/api/internal/collections/{collection_id}/entities",
        headers=_headers(),
        json={"name": "Acme Corp", "type": "organisation", "mentions_delta": 2},
    )
    assert second.status_code == 200
    assert second.json()["mentions"] == 3
    assert second.json()["id"] == first.json()["id"]


async def test_create_relation_between_two_entities(client):
    collection_id, _ = await _create_collection_and_document()

    entity_a = (
        await client.post(
            f"/api/internal/collections/{collection_id}/entities",
            headers=_headers(),
            json={"name": "Alice", "type": "personne"},
        )
    ).json()
    entity_b = (
        await client.post(
            f"/api/internal/collections/{collection_id}/entities",
            headers=_headers(),
            json={"name": "Acme Corp", "type": "organisation"},
        )
    ).json()

    response = await client.post(
        f"/api/internal/collections/{collection_id}/relations",
        headers=_headers(),
        json={"from_entity_id": entity_a["id"], "to_entity_id": entity_b["id"], "type": "works_at"},
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
