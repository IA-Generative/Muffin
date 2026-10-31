import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole

START, END = "\x02", "\x03"


def _as_user(user_id: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False)

    return override


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = _as_user("alice")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Conversation))
        await session.commit()


async def _conversation(user_id: str, title: str | None, *messages: str) -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title=title)
        session.add(conversation)
        await session.flush()
        for index, content in enumerate(messages):
            role = MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT
            session.add(Message(conversation_id=conversation.id, role=role, content=content))
        await session.commit()
        return conversation.id


async def _search(client, q: str, **params):
    return await client.get("/api/conversations/search", params={"q": q, **params})


async def test_a_word_of_a_message_finds_its_conversation_with_a_snippet(client):
    conversation_id = await _conversation("alice", "Question RH", "Combien de jours de télétravail par semaine ?")

    response = await _search(client, "télétravail")

    assert response.status_code == 200
    [hit] = response.json()["items"]
    assert hit["id"] == str(conversation_id)
    assert hit["message_id"] is not None
    assert f"{START}télétravail{END}" in hit["snippet"]
    assert hit["title_matched"] is False


async def test_accents_and_case_are_ignored(client):
    await _conversation("alice", "Vacances", "Mes CONGÉS payés de l'été")

    assert len((await _search(client, "conges")).json()["items"]) == 1
    assert len((await _search(client, "congés")).json()["items"]) == 1
    assert len((await _search(client, "CONGES")).json()["items"]) == 1


async def test_the_search_stems_french_words(client):
    await _conversation("alice", None, "Les procédures de remboursement des frais")

    assert len((await _search(client, "procédure")).json()["items"]) == 1


async def test_a_word_of_the_title_finds_a_conversation_without_a_snippet(client):
    await _conversation("alice", "Budget prévisionnel 2027", "Bonjour")

    [hit] = (await _search(client, "budget")).json()["items"]

    assert hit["title_matched"] is True
    assert hit["message_id"] is None
    assert hit["snippet"] is None


async def test_a_conversation_is_listed_once_with_its_best_message(client):
    await _conversation(
        "alice",
        "Sujet",
        "Parle-moi du télétravail",
        "Le télétravail est autorisé deux jours par semaine, le télétravail occasionnel aussi.",
        "Merci pour le télétravail",
    )

    items = (await _search(client, "télétravail")).json()["items"]

    assert len(items) == 1
    assert "autorisé" in items[0]["snippet"]


async def test_a_title_match_comes_before_a_message_match(client):
    await _conversation("alice", "Autre sujet", "Une question sur le budget")
    title_match = await _conversation("alice", "Le budget", "Bonjour")

    items = (await _search(client, "budget")).json()["items"]

    assert items[0]["id"] == str(title_match)
    assert len(items) == 2


async def test_the_conversations_of_other_users_are_never_found(client):
    await _conversation("bob", "Secret de Bob", "Le mot de passe est abracadabra")

    response = await _search(client, "abracadabra")
    assert response.json()["items"] == []
    assert response.json()["total"] == 0

    assert (await _search(client, "Secret")).json()["items"] == []


async def test_a_quoted_phrase_and_an_exclusion_are_understood(client):
    await _conversation("alice", None, "le plan de continuité d'activité")
    await _conversation("alice", None, "le plan de formation et la continuité")

    assert len((await _search(client, '"plan de continuité"')).json()["items"]) == 1
    assert len((await _search(client, "continuité -formation")).json()["items"]) == 1


async def test_nothing_found_is_an_empty_page(client):
    await _conversation("alice", "Titre", "Un message")

    body = (await _search(client, "inexistant")).json()

    assert body["items"] == []
    assert body["total"] == 0


async def test_a_query_that_is_too_short_is_refused(client):
    assert (await _search(client, "a")).status_code == 422
    assert (await _search(client, " a ")).status_code == 422


async def test_a_query_with_only_stop_words_finds_nothing_and_does_not_fail(client):
    await _conversation("alice", "Titre", "le la les de du")

    response = await _search(client, "le de")

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_the_results_are_paginated_with_the_total(client):
    for index in range(5):
        await _conversation("alice", f"Rapport {index}", "Un rapport")

    page = (await _search(client, "rapport", page_size=2, page=2)).json()

    assert page["total"] == 5
    assert len(page["items"]) == 2


async def test_the_search_route_is_not_taken_for_a_conversation_id(client):
    response = await client.get("/api/conversations/search")

    assert response.status_code == 422
    assert "uuid" not in response.text.lower()


async def test_a_message_cannot_inject_markup_through_the_snippet(client):
    await _conversation("alice", None, "<script>alert(1)</script> télétravail")

    [hit] = (await _search(client, "télétravail")).json()["items"]

    # The words found are only ever marked by control characters: the page escapes everything else.
    assert START in hit["snippet"] and END in hit["snippet"]
