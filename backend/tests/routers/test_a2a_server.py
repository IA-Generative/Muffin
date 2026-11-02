"""Muffin's assistants as A2A agents (#a2a): the agent card, and `message/send`, for a personal API key or the
assistant's own dedicated token - never for anyone else, and never when the author did not turn this on."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete

from app.core.security.factory import RequestContext
from app.db import async_session_factory
from app.main import app
from app.models.api_key import ApiKey
from app.models.assistant import Assistant
from app.models.collection import Collection
from app.models.conversation import Conversation
from app.models.run import Run
from app.services import api_key_service, assistant_service
from app.services.assistant_service import AssistantService
from tests.routers.test_openai_api import ALICE, BOB, _agent_answers, _assistant, _auth, _collection, _key

ANSWER = "12 jours restants."


@pytest.fixture(autouse=True)
def _peppers(monkeypatch):
    monkeypatch.setattr(assistant_service._api_key_settings, "API_KEY_PEPPERS", SecretStr("v1=test-pepper"))
    monkeypatch.setattr(api_key_service._settings, "API_KEY_PEPPERS", SecretStr("v1=test-pepper"))


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(ApiKey))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Assistant).where(Assistant.owner_id.in_([ALICE, BOB])))
        await session.execute(delete(Collection).where(Collection.owner_id.in_([ALICE, BOB])))
        await session.commit()


async def _token(assistant_id: uuid.UUID, owner_id: str = ALICE) -> str:
    context = RequestContext(
        user_id=owner_id, email=f"{owner_id}@example.com", roles=["user"], is_admin=False, groups=[]
    )
    async with async_session_factory() as db:
        out = await AssistantService(db).new_a2a_token(assistant_id, context)
        await db.commit()
    return out.token


def _card_url(assistant_id: uuid.UUID) -> str:
    return f"/api/a2a/assistants/{assistant_id}/.well-known/agent-card.json"


async def _rpc(client, assistant_id: uuid.UUID, token: str, message: str = "Combien de jours ?"):
    return await client.post(
        f"/api/a2a/assistants/{assistant_id}",
        headers=_auth(token),
        json={
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": message}]}},
        },
    )


# --- who may call ---


async def test_a_call_without_a_bearer_token_is_refused(client):
    assistant_id = await _assistant(ALICE, "RH Bot")

    assert (await client.get(_card_url(assistant_id))).status_code == 404


async def test_an_assistant_not_exposed_as_a2a_does_not_exist_even_for_its_owner(client):
    assistant_id = await _assistant(ALICE, "RH Bot")
    key = await _key(ALICE)

    response = await client.get(_card_url(assistant_id), headers=_auth(key))

    assert response.status_code == 404


async def test_a_wrong_or_unrelated_token_is_refused_the_same_way_as_an_unknown_one(client):
    assistant_id = await _assistant(ALICE, "RH Bot")
    other_id = await _assistant(ALICE, "Autre agent")
    real_token = await _token(assistant_id)
    other_token = await _token(other_id)

    assert (await client.get(_card_url(assistant_id), headers=_auth(other_token))).status_code == 404
    assert (await client.get(_card_url(assistant_id), headers=_auth("not-a-token"))).status_code == 404
    assert (await client.get(_card_url(assistant_id))).status_code == 404  # no header at all
    assert (await client.get(_card_url(assistant_id), headers=_auth(real_token))).status_code == 200


async def test_an_api_key_of_someone_who_cannot_use_the_assistant_is_refused(client):
    assistant_id = await _assistant(BOB, "Agent de Bob")
    await _token(assistant_id, BOB)  # exposed, but private to Bob
    key = await _key(ALICE)

    assert (await client.get(_card_url(assistant_id), headers=_auth(key))).status_code == 404


# --- the agent card ---


async def test_the_agent_card_names_the_assistant_and_its_own_url(client):
    assistant_id = await _assistant(ALICE, "RH Bot")
    token = await _token(assistant_id)

    response = await client.get(_card_url(assistant_id), headers=_auth(token))

    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "RH Bot"
    assert card["url"].endswith(f"/api/a2a/assistants/{assistant_id}")
    assert card["capabilities"] == {"streaming": False, "pushNotifications": False}
    assert card["defaultInputModes"] == ["text"] and card["defaultOutputModes"] == ["text"]


async def test_a_personal_api_key_also_reaches_the_card_of_an_assistant_one_may_use(client):
    assistant_id = await _assistant(ALICE, "RH Bot")
    await _token(assistant_id)  # turns expose_as_a2a on; the key does not need it
    key = await _key(ALICE)

    assert (await client.get(_card_url(assistant_id), headers=_auth(key))).status_code == 200


# --- message/send ---


async def test_a_message_is_answered_the_way_the_chat_with_this_assistant_would(client, monkeypatch):
    col = await _collection(ALICE, "RH")
    assistant_id = await _assistant(ALICE, "RH Bot", [col])
    token = await _token(assistant_id)
    _agent_answers(monkeypatch, ANSWER)

    response = await _rpc(client, assistant_id, token)

    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == "1"
    assert body["result"]["role"] == "agent" and body["result"]["kind"] == "message"
    assert body["result"]["parts"][0]["kind"] == "text"
    assert body["result"]["parts"][0]["text"].startswith(ANSWER)


async def test_the_dedicated_token_runs_as_the_assistants_owner_never_anyone_else(client, monkeypatch):
    assistant_id = await _assistant(BOB, "Agent de Bob")
    token = await _token(assistant_id, BOB)
    key = await _key(ALICE)  # Bob shares nothing: Alice's own key cannot reach it
    _agent_answers(monkeypatch, ANSWER)

    with_token = await _rpc(client, assistant_id, token)
    with_wrong_key = await _rpc(client, assistant_id, key)

    assert with_token.status_code == 200 and with_token.json()["result"]["parts"][0]["text"].startswith(ANSWER)
    assert with_wrong_key.status_code == 200
    assert with_wrong_key.json()["error"]["code"] == -32001


async def test_only_message_send_is_supported(client):
    assistant_id = await _assistant(ALICE, "RH Bot")
    token = await _token(assistant_id)

    response = await client.post(
        f"/api/a2a/assistants/{assistant_id}",
        headers=_auth(token),
        json={"jsonrpc": "2.0", "id": "7", "method": "tasks/get", "params": {}},
    )

    assert response.status_code == 200  # JSON-RPC errors are still a 200 with an "error" body
    body = response.json()
    assert body["id"] == "7" and body["error"]["code"] == -32601


async def test_a_message_with_no_text_part_is_refused(client):
    assistant_id = await _assistant(ALICE, "RH Bot")
    token = await _token(assistant_id)

    response = await client.post(
        f"/api/a2a/assistants/{assistant_id}",
        headers=_auth(token),
        json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": {"parts": []}}},
    )

    assert response.json()["error"]["code"] == -32602
