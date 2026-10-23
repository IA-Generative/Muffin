"""Where the entities are in the text, and the sentence behind each relation (#352)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.entity import Entity, EntityMention, Relation
from app.repositories.entity_repository import EntityRepository
from app.services.result_reuse import ResultReuse
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _collection(owner: str = "dev-user") -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner, name="Test", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.commit()
        return collection.id


async def _document(collection_id: uuid.UUID, name: str = "report.pdf") -> uuid.UUID:
    async with async_session_factory() as session:
        document = Document(collection_id=collection_id, name=name, type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return document.id


def _entity(name, type_="organisation", mentions=1, occurrences=()):
    return {
        "name": name,
        "type": type_,
        "mentions": mentions,
        "occurrences": [{"page": page, "start": start, "end": end} for page, start, end in occurrences],
    }


async def _window(client, document_id, key, entities, relations=()):
    response = await client.put(
        f"/api/internal/documents/{document_id}/entity-windows/{key}",
        json={"entities": entities, "relations": list(relations)},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text


async def _entities(client, collection_id, **query):
    return {item["name"]: item for item in (await client.get(f"/api/collections/{collection_id}/entities")).json()}


async def test_an_entity_keeps_where_it_was_found_and_says_how_many(client):
    collection_id = await _collection()
    document_id = await _document(collection_id)

    await _window(
        client,
        document_id,
        "pages:1-2",
        [
            _entity("Acme Corp", mentions=3, occurrences=[(1, 10, 19), (1, 80, 89), (2, 5, 14)]),
            # The model's own name for it, nowhere in the text: listed, with nothing to show.
            _entity("Société Acme", mentions=1),
        ],
    )

    entities = await _entities(client, collection_id)
    assert (entities["Acme Corp"]["mentions"], entities["Acme Corp"]["occurrences"]) == (3, 3)
    assert (entities["Société Acme"]["mentions"], entities["Société Acme"]["occurrences"]) == (1, 0)


async def test_the_occurrences_of_an_entity_come_in_reading_order(client):
    collection_id = await _collection()
    first, second = await _document(collection_id, "a.pdf"), await _document(collection_id, "b.pdf")
    await _window(client, second, "pages:1-1", [_entity("Acme Corp", occurrences=[(3, 7, 16)])])
    await _window(
        client, first, "pages:1-2", [_entity("Acme Corp", occurrences=[(2, 5, 14), (1, 80, 89), (1, 10, 19)])]
    )
    entity_id = (await _entities(client, collection_id))["Acme Corp"]["id"]

    response = await client.get(f"/api/collections/{collection_id}/entities/{entity_id}/mentions")

    assert [(m["document_name"], m["page_number"], m["start"], m["end"]) for m in response.json()] == [
        ("a.pdf", 1, 10, 19),
        ("a.pdf", 1, 80, 89),
        ("a.pdf", 2, 5, 14),
        ("b.pdf", 3, 7, 16),
    ]


async def test_the_occurrences_can_be_asked_for_one_document(client):
    collection_id = await _collection()
    first, second = await _document(collection_id, "a.pdf"), await _document(collection_id, "b.pdf")
    await _window(client, first, "pages:1-1", [_entity("Acme Corp", occurrences=[(1, 0, 9)])])
    await _window(client, second, "pages:1-1", [_entity("Acme Corp", occurrences=[(1, 4, 13)])])
    entity_id = (await _entities(client, collection_id))["Acme Corp"]["id"]

    response = await client.get(f"/api/collections/{collection_id}/entities/{entity_id}/mentions?document_id={second}")

    assert [(m["document_name"], m["start"]) for m in response.json()] == [("b.pdf", 4)]


async def test_a_window_extracted_again_replaces_its_occurrences_instead_of_adding_them(client):
    collection_id = await _collection()
    document_id = await _document(collection_id)
    await _window(
        client, document_id, "pages:1-2", [_entity("Acme Corp", mentions=2, occurrences=[(1, 0, 9), (1, 30, 39)])]
    )

    await _window(client, document_id, "pages:1-2", [_entity("Acme Corp", mentions=1, occurrences=[(2, 4, 13)])])

    entities = await _entities(client, collection_id)
    assert (entities["Acme Corp"]["mentions"], entities["Acme Corp"]["occurrences"]) == (1, 1)
    entity_id = entities["Acme Corp"]["id"]
    rows = (await client.get(f"/api/collections/{collection_id}/entities/{entity_id}/mentions")).json()
    assert [(m["page_number"], m["start"]) for m in rows] == [(2, 4)]


async def test_two_windows_of_a_document_each_keep_their_own_occurrences(client):
    collection_id = await _collection()
    document_id = await _document(collection_id)
    await _window(client, document_id, "pages:1-2", [_entity("Acme Corp", occurrences=[(1, 0, 9)])])
    await _window(client, document_id, "pages:2-3", [_entity("Acme Corp", occurrences=[(3, 0, 9)])])

    await _window(client, document_id, "pages:1-2", [_entity("Acme Corp", occurrences=[(2, 5, 14)])])

    entity_id = (await _entities(client, collection_id))["Acme Corp"]["id"]
    rows = (await client.get(f"/api/collections/{collection_id}/entities/{entity_id}/mentions")).json()
    assert sorted((m["page_number"], m["start"]) for m in rows) == [(2, 5), (3, 0)]


async def test_a_relation_keeps_the_sentence_behind_it_and_where_it_is(client):
    collection_id = await _collection()
    document_id = await _document(collection_id, "contrat.pdf")
    await _window(
        client,
        document_id,
        "pages:1-2",
        [_entity("Acme Corp", occurrences=[(2, 0, 9)]), _entity("Jean Dupont", "personne")],
        [
            {
                "from_name": "Jean Dupont",
                "to_name": "Acme Corp",
                "type": "dirige",
                "source_page": 2,
                "source_excerpt": "Jean Dupont dirige Acme Corp.",
                "source_start": 120,
                "source_end": 149,
            },
            {"from_name": "Acme Corp", "to_name": "Jean Dupont", "type": "emploie"},
        ],
    )

    relations = {r["type"]: r for r in (await client.get(f"/api/collections/{collection_id}/relations")).json()}

    assert relations["dirige"]["source"] == {
        "document_id": str(document_id),
        "document_name": "contrat.pdf",
        "page_number": 2,
        "passage": "Jean Dupont dirige Acme Corp.",
        "start": 120,
        "end": 149,
    }
    # One whose sentence was not found: shown as before, with nothing to open.
    assert relations["emploie"]["source"] is None


async def test_the_entities_of_a_document_count_their_occurrences_in_that_document_only(client):
    collection_id = await _collection()
    first, second = await _document(collection_id, "a.pdf"), await _document(collection_id, "b.pdf")
    await _window(client, first, "pages:1-1", [_entity("Acme Corp", occurrences=[(1, 0, 9)])])
    await _window(client, second, "pages:1-1", [_entity("Acme Corp", mentions=2, occurrences=[(1, 0, 9), (1, 40, 49)])])

    response = await client.get(f"/api/collections/{collection_id}/documents/{first}/entities")

    assert [(e["name"], e["occurrences"]) for e in response.json()] == [("Acme Corp", 1)]


async def test_the_occurrences_of_an_entity_of_another_collection_are_not_given(client):
    collection_id, other_id = await _collection(), await _collection()
    document_id = await _document(other_id)
    await _window(client, document_id, "pages:1-1", [_entity("Acme Corp", occurrences=[(1, 0, 9)])])
    entity_id = (await _entities(client, other_id))["Acme Corp"]["id"]

    response = await client.get(f"/api/collections/{collection_id}/entities/{entity_id}/mentions")

    assert response.status_code == 200 and response.json() == []


async def test_a_stranger_cannot_read_the_occurrences_of_a_private_collection(client):
    collection_id = await _collection(owner="owner")
    document_id = await _document(collection_id)
    await _window(client, document_id, "pages:1-1", [_entity("Acme Corp", occurrences=[(1, 0, 9)])])
    async with async_session_factory() as session:
        entity_id = await session.scalar(select(Entity.id).where(Entity.collection_id == collection_id))
    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")

    response = await client.get(f"/api/collections/{collection_id}/entities/{entity_id}/mentions")

    assert response.status_code == 404


async def test_what_a_document_contributed_goes_with_it_occurrences_and_sentences_included(client):
    collection_id = await _collection()
    document_id = await _document(collection_id)
    await _window(
        client,
        document_id,
        "pages:1-1",
        [_entity("Acme Corp", occurrences=[(1, 0, 9)]), _entity("Jean Dupont", "personne", occurrences=[(1, 20, 31)])],
        [
            {
                "from_name": "Jean Dupont",
                "to_name": "Acme Corp",
                "type": "dirige",
                "source_page": 1,
                "source_excerpt": "Jean dirige Acme.",
            }
        ],
    )

    async with async_session_factory() as session:
        await EntityRepository(session).remove_document(document_id)
        await session.commit()

    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(EntityMention)) == 0
        assert await session.scalar(select(func.count()).select_from(Relation)) == 0


async def test_a_document_that_reuses_another_s_extraction_has_the_same_occurrences_and_sentences(client):
    collection_id = await _collection()
    source_id, target_id = await _document(collection_id, "a.pdf"), await _document(collection_id, "copy.pdf")
    await _window(
        client,
        source_id,
        "pages:1-2",
        [_entity("Acme Corp", mentions=2, occurrences=[(1, 0, 9), (2, 30, 39)]), _entity("Jean Dupont", "personne")],
        [
            {
                "from_name": "Jean Dupont",
                "to_name": "Acme Corp",
                "type": "dirige",
                "source_page": 2,
                "source_excerpt": "Jean Dupont dirige Acme Corp.",
                "source_start": 100,
                "source_end": 129,
            }
        ],
    )

    async with async_session_factory() as session:
        source, target = await session.get(Document, source_id), await session.get(Document, target_id)
        await ResultReuse(session)._copy_entities(source, target, [])
        await session.commit()

    async with async_session_factory() as session:
        copied = (
            await session.execute(
                select(EntityMention.page_number, EntityMention.char_start).where(
                    EntityMention.document_id == target_id
                )
            )
        ).all()
        relation = await session.scalar(select(Relation).where(Relation.document_id == target_id))
    assert sorted(copied) == [(1, 0), (2, 30)]
    assert (relation.source_page, relation.source_excerpt, relation.source_start, relation.source_end) == (
        2,
        "Jean Dupont dirige Acme Corp.",
        100,
        129,
    )
