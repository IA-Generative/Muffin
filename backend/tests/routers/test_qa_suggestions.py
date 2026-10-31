"""Starter questions on an empty chat (#126), and their answer - the pair's own, with its source."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings, CollectionVisibility
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.qa import QaOrigin, QaPair
from app.models.run import Run


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection))
        await session.commit()


def _as_user(user_id: str, groups: list[str] | None = None):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id, email=f"{user_id}@example.org", roles=["user"], is_admin=False, groups=groups or []
        )

    return override


async def _collection(owner: str = "dev-user", name: str = "RH", **fields) -> Collection:
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner, name=name, description="", **fields)
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.commit()
        return collection


async def _document(collection_id, name: str = "teletravail.pdf", chunks: list[tuple[str, int]] | None = None):
    async with async_session_factory() as session:
        document = Document(collection_id=collection_id, name=name, type="url")
        session.add(document)
        await session.flush()
        for index, (text, page) in enumerate(chunks or []):
            session.add(
                Chunk(
                    document_id=document.id,
                    index=index,
                    text=text,
                    token_count=10,
                    extras={"page_start": page, "page_end": page},
                )
            )
        await session.commit()
        return document


async def _pair(collection_id, document_id, question="Combien de jours de télétravail ?", **fields) -> QaPair:
    values = {"answer": "Deux jours par semaine.", "origin": QaOrigin.GENERATED, "validated": True} | fields
    async with async_session_factory() as session:
        pair = QaPair(collection_id=collection_id, document_id=document_id, question=question, **values)
        session.add(pair)
        await session.commit()
        return pair


# -- the suggestions ----------------------------------------------------------------------------


async def test_suggests_questions_of_the_collections_the_user_can_read(client):
    collection = await _collection()
    document = await _document(collection.id)
    pair = await _pair(collection.id, document.id)

    response = await client.get("/api/qa-suggestions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(pair.id),
            "question": pair.question,
            "collection_id": str(collection.id),
            "collection_name": "RH",
        }
    ]


async def test_at_most_three_suggestions_and_never_the_same_twice(client):
    collection = await _collection()
    document = await _document(collection.id)
    for index in range(6):
        await _pair(collection.id, document.id, question=f"Question {index} ?")

    body = (await client.get("/api/qa-suggestions")).json()

    assert len(body) == 3
    assert len({item["id"] for item in body}) == 3


async def test_reviewed_pairs_come_first_and_generated_ones_only_fill_up(client):
    collection = await _collection()
    document = await _document(collection.id)
    reviewed = [await _pair(collection.id, document.id, question=f"Relue {i} ?", validated=True) for i in range(2)]
    for index in range(5):
        await _pair(collection.id, document.id, question=f"Générée {index} ?", validated=False)

    body = (await client.get("/api/qa-suggestions")).json()

    assert len(body) == 3
    assert {str(pair.id) for pair in reviewed} <= {item["id"] for item in body}


async def test_never_a_golden_pair_nor_one_without_a_document_nor_another_users_private_one(client):
    mine = await _collection()
    document = await _document(mine.id)
    await _pair(mine.id, document.id, question="Golden ?", golden=True)
    await _pair(mine.id, None, question="Sans document ?")
    other = await _collection(owner="someone-else", name="Privée")
    other_document = await _document(other.id)
    await _pair(other.id, other_document.id, question="Privée ?")

    assert (await client.get("/api/qa-suggestions")).json() == []


async def test_a_public_collection_of_someone_else_is_readable_and_so_suggested(client):
    other = await _collection(owner="someone-else", name="Publique", visibility=CollectionVisibility.PUBLIC)
    document = await _document(other.id)
    await _pair(other.id, document.id, question="Publique ?")

    body = (await client.get("/api/qa-suggestions")).json()

    assert [item["question"] for item in body] == ["Publique ?"]


async def test_pinned_collections_narrow_the_suggestions_to_them_and_what_is_below(client):
    first = await _collection(name="Première")
    second = await _collection(name="Seconde")
    for collection in (first, second):
        document = await _document(collection.id)
        await _pair(collection.id, document.id, question=f"De {collection.name} ?")

    body = (await client.get("/api/qa-suggestions", params={"collection_ids": [str(second.id)]})).json()

    assert [item["question"] for item in body] == ["De Seconde ?"]


async def test_pinning_a_collection_the_user_cannot_read_gives_nothing(client):
    other = await _collection(owner="someone-else")
    document = await _document(other.id)
    await _pair(other.id, document.id)

    assert (await client.get("/api/qa-suggestions", params={"collection_ids": [str(other.id)]})).json() == []


# -- the answer ---------------------------------------------------------------------------------


async def test_asking_a_suggestion_answers_with_the_stored_answer_and_its_source(client):
    collection = await _collection()
    document = await _document(collection.id)
    pair = await _pair(
        collection.id,
        document.id,
        source_page=4,
        source_excerpt="Le télétravail est autorisé deux jours par semaine.",
    )

    response = await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})

    assert response.status_code == 201
    conversation_id = response.json()["conversation_id"]
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assert [(message["role"], message["content"]) for message in messages] == [
        ("user", pair.question),
        ("assistant", f"Deux jours par semaine. [{pair.id}]"),
    ]
    (citation,) = messages[1]["citations"]
    assert citation["source"] == "teletravail.pdf"
    assert citation["document_id"] == str(document.id)
    assert citation["page_number"] == 4
    assert citation["content"] == "Le télétravail est autorisé deux jours par semaine."
    assert citation["vdb_path"] == ["RH"]
    assert citation["source_id"]  # a real Source row: feedback can validate it


async def test_it_never_goes_through_the_research_agent(client):
    from unittest.mock import patch

    collection = await _collection()
    document = await _document(collection.id)
    pair = await _pair(collection.id, document.id)

    with patch("app.services.run_service.agent_runner.start") as enqueue:
        response = await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})

    assert response.status_code == 201
    enqueue.assert_not_called()
    async with async_session_factory() as session:
        run = await session.get(Run, response.json()["run_id"])
    assert run.status == "completed" and run.celery_task_id is None


async def test_the_page_and_passage_of_an_older_pair_are_found_in_its_document(client):
    collection = await _collection()
    document = await _document(
        collection.id,
        chunks=[
            ("Introduction générale au document. Les congés sont décrits plus loin.", 1),
            ("Le télétravail est autorisé jusqu'à deux jours par semaine après accord du responsable.", 3),
        ],
    )
    pair = await _pair(
        collection.id,
        document.id,
        answer="Le télétravail est autorisé deux jours par semaine avec accord du responsable.",
    )

    response = await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})

    messages = (await client.get(f"/api/conversations/{response.json()['conversation_id']}/messages")).json()
    (citation,) = messages[1]["citations"]
    assert citation["page_number"] == 3
    assert "deux jours par semaine" in citation["content"]
    assert citation["chunk_id"]
    # Kept: the next time it is shown, nothing is searched again.
    async with async_session_factory() as session:
        stored = await session.get(QaPair, pair.id)
    assert stored.source_page == 3 and stored.source_excerpt


async def test_a_pair_whose_passage_cannot_be_found_is_shown_with_its_document_only(client):
    collection = await _collection()
    document = await _document(collection.id, chunks=[("Un texte sans rapport avec la réponse donnée.", 1)])
    pair = await _pair(collection.id, document.id, answer="Réponse totalement différente et inventée ici.")

    response = await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})

    messages = (await client.get(f"/api/conversations/{response.json()['conversation_id']}/messages")).json()
    (citation,) = messages[1]["citations"]
    assert citation["document_id"] == str(document.id)
    assert citation["page_number"] is None and citation["content"] is None


async def test_the_answer_can_go_into_an_existing_conversation_of_the_user(client):
    collection = await _collection()
    document = await _document(collection.id)
    pair = await _pair(collection.id, document.id)
    first = (await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})).json()

    again = await client.post(
        f"/api/qa-suggestions/{pair.id}/answer", json={"conversation_id": first["conversation_id"]}
    )

    assert again.json()["conversation_id"] == first["conversation_id"]
    messages = (await client.get(f"/api/conversations/{first['conversation_id']}/messages")).json()
    assert len(messages) == 4


async def test_a_pair_the_user_cannot_read_is_a_404(client):
    other = await _collection(owner="someone-else")
    document = await _document(other.id)
    pair = await _pair(other.id, document.id)

    response = await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})

    assert response.status_code == 404


async def test_a_golden_pair_cannot_be_asked(client):
    collection = await _collection()
    document = await _document(collection.id)
    pair = await _pair(collection.id, document.id, golden=True)

    assert (await client.post(f"/api/qa-suggestions/{pair.id}/answer", json={})).status_code == 404


async def test_someone_elses_conversation_is_a_404(client):
    collection = await _collection()
    document = await _document(collection.id)
    pair = await _pair(collection.id, document.id)
    app.dependency_overrides[get_current_user] = _as_user("another-user")
    other_collection = await _collection(owner="another-user", name="À lui")
    other_document = await _document(other_collection.id)
    other_pair = await _pair(other_collection.id, other_document.id)
    theirs = (await client.post(f"/api/qa-suggestions/{other_pair.id}/answer", json={})).json()
    app.dependency_overrides.pop(get_current_user, None)

    response = await client.post(
        f"/api/qa-suggestions/{pair.id}/answer", json={"conversation_id": theirs["conversation_id"]}
    )

    assert response.status_code == 404
