"""A document read again with other settings keeps only what its windows now are, and a summary says which pages it was
made from (#372)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.entity import Entity, EntityDocument, Relation
from app.models.qa import QaPair

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture(autouse=True)
def vectors(monkeypatch):
    """The search engine is not what is tested here: what is asked of it is recorded."""
    from unittest.mock import MagicMock

    from app.services import document_derived_data

    store = MagicMock()
    monkeypatch.setattr(document_derived_data, "vector_store", store)
    return store


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


def _headers():
    return {"X-API-Key": API_KEY}


async def _document() -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Test", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="report.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def _qa(client, collection_id, document_id, key, question):
    response = await client.put(
        f"/api/internal/collections/{collection_id}/qa-pairs/generated",
        headers=_headers(),
        json={"document_id": str(document_id), "key": key, "pairs": [{"question": question, "answer": "A."}]},
    )
    assert response.status_code == 200, response.text


async def _entities(client, document_id, window, name):
    response = await client.put(
        f"/api/internal/documents/{document_id}/entity-windows/{window}",
        headers=_headers(),
        json={"entities": [{"name": name, "type": "personne"}], "relations": []},
    )
    assert response.status_code == 200, response.text


async def _questions(collection_id) -> list[str]:
    async with async_session_factory() as session:
        rows = await session.execute(select(QaPair).where(QaPair.collection_id == collection_id))
        return sorted(pair.question for pair in rows.scalars())


async def _entity_names(collection_id) -> list[str]:
    async with async_session_factory() as session:
        rows = await session.execute(select(Entity).where(Entity.collection_id == collection_id))
        return sorted(entity.name for entity in rows.scalars())


async def _prune(client, document_id, **body):
    return await client.post(f"/api/internal/documents/{document_id}/windows/prune", headers=_headers(), json=body)


async def test_the_pairs_of_windows_that_are_no_longer_read_go_with_their_vectors(client, vectors):
    collection_id, document_id = await _document()
    for window, question in (("window:1-2", "A?"), ("window:3-4", "B?"), ("window:5-6", "C?")):
        await _qa(client, collection_id, document_id, window, question)

    response = await _prune(client, document_id, qa=["window:1-2", "window:5-6"])

    assert response.status_code == 200
    assert await _questions(collection_id) == ["A?", "C?"]
    removed_collection, removed_ids = vectors.delete_qa_embeddings.call_args_list[-1].args
    assert removed_collection == collection_id and len(removed_ids) == 1


async def test_what_a_person_validated_and_what_is_not_a_window_stays(client):
    collection_id, document_id = await _document()
    await _qa(client, collection_id, document_id, "window:1-2", "Validated?")
    await _qa(client, collection_id, document_id, "tabular", "From the profile?")
    await _qa(client, collection_id, document_id, "window:3-4", "Dropped?")
    async with async_session_factory() as session:
        await session.execute(update(QaPair).where(QaPair.question == "Validated?").values(validated=True))
        await session.commit()

    await _prune(client, document_id, qa=[])

    assert await _questions(collection_id) == ["From the profile?", "Validated?"]


async def test_the_other_documents_of_the_collection_are_left_alone(client):
    collection_id, document_id = await _document()
    async with async_session_factory() as session:
        other = Document(collection_id=collection_id, name="other.pdf", type="file", storage_key="k2")
        session.add(other)
        await session.commit()
        other_id = other.id
    await _qa(client, collection_id, document_id, "window:1-2", "Mine?")
    await _qa(client, collection_id, other_id, "window:1-2", "Theirs?")

    await _prune(client, document_id, qa=[])

    assert await _questions(collection_id) == ["Theirs?"]


async def test_the_entities_of_windows_that_are_no_longer_read_leave_the_collection(client):
    collection_id, document_id = await _document()
    await _entities(client, document_id, "pages:1-4", "Alice")
    await _entities(client, document_id, "pages:5-8", "Bob")
    await _entities(client, document_id, "pages:9-12", "Carol")

    response = await _prune(client, document_id, entities=["pages:5-8"])

    assert response.status_code == 200
    assert await _entity_names(collection_id) == ["Bob"]


async def test_an_entity_still_mentioned_by_a_kept_window_stays_with_its_remaining_mentions(client):
    collection_id, document_id = await _document()
    await _entities(client, document_id, "pages:1-4", "Alice")
    await _entities(client, document_id, "pages:5-8", "Alice")

    await _prune(client, document_id, entities=["pages:1-4"])

    async with async_session_factory() as session:
        (alice,) = (await session.execute(select(Entity).where(Entity.collection_id == collection_id))).scalars().all()
        links = (
            (await session.execute(select(EntityDocument).where(EntityDocument.entity_id == alice.id))).scalars().all()
        )
    assert alice.mentions == 1 and [link.window_key for link in links] == ["pages:1-4"]


async def test_the_relations_of_a_window_that_goes_go_with_it(client):
    collection_id, document_id = await _document()
    response = await client.put(
        f"/api/internal/documents/{document_id}/entity-windows/pages:1-4",
        headers=_headers(),
        json={
            "entities": [{"name": "Alice", "type": "personne"}, {"name": "Acme", "type": "organisation"}],
            "relations": [{"from_name": "Alice", "to_name": "Acme", "type": "works_at"}],
        },
    )
    assert response.status_code == 200
    await _entities(client, document_id, "pages:5-8", "Bob")

    await _prune(client, document_id, entities=["pages:5-8"])

    async with async_session_factory() as session:
        assert (await session.execute(select(Relation).where(Relation.collection_id == collection_id))).first() is None


async def test_a_step_that_is_not_given_is_left_alone(client):
    collection_id, document_id = await _document()
    await _qa(client, collection_id, document_id, "window:1-2", "A?")
    await _entities(client, document_id, "pages:1-4", "Alice")

    assert (await _prune(client, document_id)).status_code == 200
    assert (await _prune(client, document_id, qa=["window:1-2"])).status_code == 200

    assert await _questions(collection_id) == ["A?"]
    assert await _entity_names(collection_id) == ["Alice"]


async def test_pruning_an_unknown_document_is_a_404(client):
    assert (await _prune(client, uuid.uuid4(), qa=[])).status_code == 404


# -- the pages a summary was made from -----------------------------------------------------------------------------


async def _summary_pages(document_id):
    async with async_session_factory() as session:
        return (await session.get(Document, document_id)).summary_pages


async def test_a_summary_remembers_the_pages_it_was_made_from(client):
    _, document_id = await _document()

    response = await client.patch(
        f"/api/internal/documents/{document_id}/summary",
        headers=_headers(),
        json={"summary": "The start and the end.", "pages": [[1, 135], [766, 900]]},
    )

    assert response.status_code == 200
    assert await _summary_pages(document_id) == [[1, 135], [766, 900]]


async def test_a_summary_of_the_whole_document_has_no_pages_and_replaces_a_partial_one(client):
    _, document_id = await _document()
    url = f"/api/internal/documents/{document_id}/summary"
    await client.patch(url, headers=_headers(), json={"summary": "Part.", "pages": [[1, 10]]})

    await client.patch(url, headers=_headers(), json={"summary": "Everything."})

    assert await _summary_pages(document_id) is None


@pytest.mark.parametrize("pages", [[[1]], [[1, 2, 3]], [["a", "b"]]])
async def test_pages_that_are_not_pairs_of_numbers_are_refused(client, pages):
    _, document_id = await _document()

    response = await client.patch(
        f"/api/internal/documents/{document_id}/summary", headers=_headers(), json={"summary": "S.", "pages": pages}
    )

    assert response.status_code == 422
    assert await _summary_pages(document_id) is None


async def test_the_agent_is_told_which_pages_a_summary_covers(client):
    collection_id, document_id = await _document()
    await client.patch(
        f"/api/internal/documents/{document_id}/summary",
        headers=_headers(),
        json={"summary": "Start and end.", "pages": [[1, 10], [90, 100]]},
    )

    response = await client.get(
        f"/api/internal/users/dev-user/collections/{collection_id}/documents", headers=_headers()
    )

    assert response.status_code == 200
    assert response.json()[0]["summary_pages"] == [[1, 10], [90, 100]]
