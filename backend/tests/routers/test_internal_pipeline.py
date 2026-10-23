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


@pytest.fixture
def vectors(monkeypatch):
    """Meilisearch replaced: what is indexed and what is removed, by QA pair id."""
    from app.services import vector_store

    calls = {"upserted": [], "deleted": []}
    monkeypatch.setattr(
        vector_store,
        "upsert_qa_embedding",
        lambda collection_id, qa_pair_id, embedding, text, model: calls["upserted"].append((qa_pair_id, text)),
    )
    monkeypatch.setattr(vector_store, "delete_qa_embeddings", lambda collection_id, ids: calls["deleted"].extend(ids))
    return calls


def _pair(question: str, **fields) -> dict:
    return {"question": question, "answer": f"Answer to {question}", **fields}


async def _replace_qa(client, collection_id, document_id, key, pairs):
    return await client.put(
        f"/api/internal/collections/{collection_id}/qa-pairs/generated",
        headers=_headers(),
        json={"document_id": None if document_id is None else str(document_id), "key": key, "pairs": pairs},
    )


async def _qa_pairs(collection_id):
    from sqlalchemy import select

    from app.models.qa import QaPair

    async with async_session_factory() as session:
        result = await session.execute(select(QaPair).where(QaPair.collection_id == collection_id))
        return sorted(result.scalars().all(), key=lambda pair: pair.question)


async def test_replace_generated_qa_records_the_pairs_of_a_run(client, vectors):
    collection_id, document_id = await _create_collection_and_document()

    response = await _replace_qa(
        client,
        collection_id,
        document_id,
        "window:1-2",
        [
            _pair(
                "What is this?",
                source_page=7,
                source_excerpt="This document is a report.",
                source_start=120,
                source_end=146,
                embedding=[0.1, 0.2],
            )
        ],
    )

    assert response.status_code == 200
    (pair,) = await _qa_pairs(collection_id)
    assert (pair.question, pair.origin, pair.document_id) == ("What is this?", "generated", document_id)
    assert (pair.source_page, pair.source_excerpt) == (7, "This document is a report.")
    # Where the passage is in its page (#351).
    assert (pair.source_start, pair.source_end) == (120, 146)
    assert pair.generation_key == "window:1-2" and pair.validated is False
    assert vectors["upserted"] == [(pair.id, "What is this?")]


async def test_a_run_replayed_leaves_the_same_pairs_not_a_second_set(client, vectors):
    """The model words every run differently, so the second run's pairs are not the first's: the run is
    what is replaced, and the first's vectors go with it."""
    collection_id, document_id = await _create_collection_and_document()
    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("A?", embedding=[0.1]), _pair("B?")])
    first_ids = {pair.id for pair in await _qa_pairs(collection_id)}

    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("C?", embedding=[0.2]), _pair("D?")])

    pairs = await _qa_pairs(collection_id)
    assert [pair.question for pair in pairs] == ["C?", "D?"]
    assert first_ids.isdisjoint(pair.id for pair in pairs)
    assert set(vectors["deleted"]) == first_ids


async def test_two_windows_of_a_document_do_not_replace_each_other(client, vectors):
    collection_id, document_id = await _create_collection_and_document()
    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("A?")])
    await _replace_qa(client, collection_id, document_id, "window:2-3", [_pair("B?")])

    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("A again?")])

    assert [pair.question for pair in await _qa_pairs(collection_id)] == ["A again?", "B?"]


async def test_a_run_that_generates_nothing_still_replaces_the_previous_one(client, vectors):
    collection_id, document_id = await _create_collection_and_document()
    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("A?")])

    await _replace_qa(client, collection_id, document_id, "window:1-2", [])

    assert await _qa_pairs(collection_id) == []


async def test_a_pair_a_person_validated_survives_its_run_being_replaced(client, vectors):
    from sqlalchemy import update

    from app.models.qa import QaPair

    collection_id, document_id = await _create_collection_and_document()
    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("Keep?"), _pair("Drop?")])
    async with async_session_factory() as session:
        await session.execute(update(QaPair).where(QaPair.question == "Keep?").values(validated=True))
        await session.commit()

    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("New?")])

    assert [pair.question for pair in await _qa_pairs(collection_id)] == ["Keep?", "New?"]


async def test_the_pairs_about_a_whole_collection_are_replaced_by_their_key_too(client, vectors):
    collection_id, document_id = await _create_collection_and_document()
    await _replace_qa(client, collection_id, None, "collection:abc", [_pair("About the collection?")])
    await _replace_qa(client, collection_id, None, "collection:def", [_pair("About its new description?")])
    await _replace_qa(client, collection_id, document_id, "window:1-2", [_pair("About a document?")])

    await _replace_qa(client, collection_id, None, "collection:abc", [_pair("Again?")])

    # Another description's pairs accumulate, as they always did; a replay replaces only its own.
    assert [pair.question for pair in await _qa_pairs(collection_id)] == [
        "About a document?",
        "About its new description?",
        "Again?",
    ]


async def test_replace_generated_qa_unknown_collection(client, vectors):
    response = await _replace_qa(client, uuid.uuid4(), None, "tabular", [_pair("A?")])

    assert response.status_code == 404


async def _replace_entities(client, document_id, window, entities, relations=()):
    return await client.put(
        f"/api/internal/documents/{document_id}/entity-windows/{window}",
        headers=_headers(),
        json={"entities": entities, "relations": list(relations)},
    )


async def _entities(collection_id) -> dict[str, int]:
    from sqlalchemy import select

    from app.models.entity import Entity

    async with async_session_factory() as session:
        result = await session.execute(select(Entity).where(Entity.collection_id == collection_id))
        return {entity.name: entity.mentions for entity in result.scalars().all()}


async def _relations(collection_id) -> list[str]:
    from sqlalchemy import select

    from app.models.entity import Relation

    async with async_session_factory() as session:
        result = await session.execute(select(Relation).where(Relation.collection_id == collection_id))
        return sorted(relation.type for relation in result.scalars().all())


ACME = {"name": "Acme Corp", "type": "organisation"}
ALICE = {"name": "Alice", "type": "personne"}
WORKS_AT = {"from_name": "Alice", "to_name": "Acme Corp", "type": "works_at"}


async def test_entities_of_a_window_are_recorded_with_their_mentions_and_relations(client):
    collection_id, document_id = await _create_collection_and_document()

    response = await _replace_entities(
        client, document_id, "pages:1-2", [ACME, {**ACME, "mentions": 2}, ALICE], [WORKS_AT]
    )

    assert response.status_code == 200
    # The same entity listed twice is one entity mentioned three times.
    assert await _entities(collection_id) == {"Acme Corp": 3, "Alice": 1}
    assert await _relations(collection_id) == ["works_at"]


async def test_a_window_extracted_twice_does_not_count_its_mentions_twice(client):
    collection_id, document_id = await _create_collection_and_document()
    await _replace_entities(client, document_id, "pages:1-2", [ACME, ALICE], [WORKS_AT])

    await _replace_entities(client, document_id, "pages:1-2", [ACME, ALICE], [WORKS_AT])

    assert await _entities(collection_id) == {"Acme Corp": 1, "Alice": 1}
    assert await _relations(collection_id) == ["works_at"]


async def test_what_the_new_extraction_no_longer_finds_goes(client):
    collection_id, document_id = await _create_collection_and_document()
    await _replace_entities(client, document_id, "pages:1-2", [ACME, ALICE], [WORKS_AT])

    await _replace_entities(client, document_id, "pages:1-2", [ACME])

    assert await _entities(collection_id) == {"Acme Corp": 1}
    assert await _relations(collection_id) == []


async def test_windows_and_documents_add_up_and_a_replay_takes_back_only_its_own(client):
    collection_id, document_id = await _create_collection_and_document()
    async with async_session_factory() as session:
        other = Document(collection_id=collection_id, name="memo.pdf", type="file", storage_key="m")
        session.add(other)
        await session.commit()
        other_id = other.id
    await _replace_entities(client, document_id, "pages:1-2", [ACME])
    await _replace_entities(client, document_id, "pages:2-3", [ACME])
    await _replace_entities(client, other_id, "pages:1-2", [ACME])
    assert await _entities(collection_id) == {"Acme Corp": 3}

    await _replace_entities(client, document_id, "pages:1-2", [ACME])
    assert await _entities(collection_id) == {"Acme Corp": 3}
    await _replace_entities(client, document_id, "pages:1-2", [])

    assert await _entities(collection_id) == {"Acme Corp": 2}


async def test_a_relation_naming_an_entity_that_was_not_extracted_is_dropped(client):
    collection_id, document_id = await _create_collection_and_document()

    await _replace_entities(client, document_id, "pages:1-2", [ACME], [WORKS_AT])

    assert await _relations(collection_id) == []


async def test_an_unknown_entity_type_is_refused(client):
    _, document_id = await _create_collection_and_document()

    response = await _replace_entities(client, document_id, "pages:1-2", [{"name": "x", "type": "robot"}])

    assert response.status_code == 422


async def test_replace_entity_window_unknown_document(client):
    response = await _replace_entities(client, uuid.uuid4(), "pages:1-2", [ACME])

    assert response.status_code == 404


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


async def test_update_collection_description_embedding_not_found(client):
    response = await client.patch(
        f"/api/internal/collections/{uuid.uuid4()}/description-embedding",
        headers=_headers(),
        json={"embedding": [0.1]},
    )
    assert response.status_code == 404


async def test_update_collection_description_embedding_indexes_in_meilisearch(client, monkeypatch):
    """Not persisted anywhere in Postgres (§124: the embedding lives in Meilisearch only) -
    this endpoint's whole job is calling vector_store, so that's the only thing worth asserting
    on. Two calls, to confirm the second one's embedding is what actually reaches Meilisearch
    (a full replace, not an accumulation)."""
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

    first = await client.patch(
        f"/api/internal/collections/{collection_id}/description-embedding",
        headers=_headers(),
        json={"embedding": [0.1, 0.2]},
    )
    second = await client.patch(
        f"/api/internal/collections/{collection_id}/description-embedding",
        headers=_headers(),
        json={"embedding": [0.4, 0.5]},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [
        (collection_id, "A collection about widgets.", ["widgets"], [0.1, 0.2]),
        (collection_id, "A collection about widgets.", ["widgets"], [0.4, 0.5]),
    ]


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
        json={"embedding": [0.1]},
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
