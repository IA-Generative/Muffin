"""The assistants (#514): named settings for the chat, shared like collections - and never a way to a collection the
person using them cannot read."""

import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security.factory import RequestContext, get_current_user
from app.core.sharing import hash_identifier, normalize_email, normalize_group
from app.db import async_session_factory
from app.main import app
from app.models.assistant import Assistant
from app.models.collection import Collection, CollectionVisibility
from app.models.conversation import Conversation
from app.models.run import Run
from app.repositories.assistant_repository import AssistantRepository
from app.services import assistant_service

ALICE, BOB, CARL = "alice", "bob", "carl"
ADMIN = "root"


def _as(user_id: str, *, groups: list[str] | None = None, admin: bool = False):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=admin, groups=groups or []
        )

    return override


@pytest.fixture
async def client():
    app.dependency_overrides[get_current_user] = _as(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Assistant))
        await session.execute(delete(Collection))
        await session.commit()


def become(user_id: str, **kwargs) -> None:
    app.dependency_overrides[get_current_user] = _as(user_id, **kwargs)


async def collection(name: str, owner: str = ALICE, *, public: bool = False) -> uuid.UUID:
    async with async_session_factory() as session:
        row = Collection(
            owner_id=owner,
            name=name,
            visibility=CollectionVisibility.PUBLIC if public else CollectionVisibility.PRIVATE,
        )
        session.add(row)
        await session.commit()
        return row.id


async def make(client, **fields) -> dict:
    response = await client.post("/api/assistants", json={"name": "RH - congés", **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def share_with(client, assistant: dict, *, email: str | None = None, group: str | None = None, **extra) -> dict:
    body = {"subject_type": "user", "identifier": email} if email else {"subject_type": "group", "identifier": group}
    response = await client.post(f"/api/assistants/{assistant['id']}/shares", json={**body, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def logs_in(user_id: str, *, email: str | None = None, groups: list[str] | None = None) -> None:
    """What the login does for the invitations typed under this email and these groups."""
    async with async_session_factory() as session:
        repository = AssistantRepository(session)
        if email:
            await repository.resolve_pending_user_shares(hash_identifier(normalize_email(email)), user_id)
        for group in groups or []:
            await repository.resolve_pending_group_shares(hash_identifier(normalize_group(group)), group)
        await session.commit()


async def run_with(client, assistant_id, **body):
    with patch("app.services.run_service.agent_runner.start"):
        return await client.post(
            "/api/runs", json={"query": "Combien de jours ?", "assistant_id": assistant_id, **body}
        )


async def stored_run() -> Run:
    async with async_session_factory() as session:
        return (await session.execute(select(Run))).scalar_one()


# --- making and reading ---


async def test_an_assistant_keeps_what_it_was_given_and_starts_at_version_one(client):
    conges = await collection("Congés")

    created = await make(
        client,
        description="Répond comme le service RH",
        icon="🏖️",
        instructions="Ton chaleureux.",
        collection_ids=[str(conges)],
        suggestions=["  Combien de jours ?  ", "", "Et pour un mariage ?"],
    )

    assert created["version"] == 1 and created["visibility"] == "private"
    assert created["is_owner"] and created["can_edit"]
    assert created["collections"] == [{"id": str(conges), "name": "Congés"}]
    assert created["suggestions"] == ["Combien de jours ?", "Et pour un mariage ?"]
    assert [a["id"] for a in (await client.get("/api/assistants")).json()] == [created["id"]]


async def test_nobody_designates_a_collection_they_cannot_read(client):
    secret = await collection("Secret", owner=BOB)
    conges = await collection("Congés")

    created = await make(client, collection_ids=[str(conges), str(secret)])

    assert [c["name"] for c in created["collections"]] == ["Congés"]
    async with async_session_factory() as session:
        stored = (await session.execute(select(Assistant))).scalar_one()
    assert stored.collection_ids == [str(conges)]


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "   "},
        {"instructions": "x" * 4001},
        {"suggestions": ["a"] * 7},
        {"suggestions": ["x" * 201]},
    ],
)
async def test_what_cannot_be_an_assistant_is_refused(client, fields):
    response = await client.post("/api/assistants", json={"name": "RH", **fields})

    assert response.status_code == 422


async def test_an_assistant_is_private_to_its_author_whoever_asks_even_directly(client):
    mine = await make(client)
    become(BOB)

    assert (await client.get("/api/assistants")).json() == []
    assert (await client.get(f"/api/assistants/{mine['id']}")).status_code == 404
    assert (await client.patch(f"/api/assistants/{mine['id']}", json={"name": "À moi"})).status_code == 404
    assert (await client.delete(f"/api/assistants/{mine['id']}")).status_code == 404
    assert (await client.post(f"/api/assistants/{mine['id']}/duplicate")).status_code == 404
    assert (await client.get(f"/api/assistants/{mine['id']}/shares")).status_code == 404
    assert (await run_with(client, mine["id"])).status_code == 404


async def test_the_limit_of_assistants_per_author_is_kept(client, monkeypatch):
    monkeypatch.setattr(assistant_service._settings, "ASSISTANTS_PER_USER", 1)
    await make(client)

    assert (await client.post("/api/assistants", json={"name": "Deux"})).status_code == 409


# --- changing: versions ---


async def test_each_change_raises_the_version_and_a_change_to_nothing_does_not(client):
    created = await make(client, instructions="Ton chaleureux.")
    url = f"/api/assistants/{created['id']}"

    same = await client.patch(url, json={"instructions": "Ton chaleureux.", "name": "RH - congés"})
    changed = await client.patch(url, json={"instructions": "Ton sérieux."})

    assert same.json()["version"] == 1
    assert changed.json()["version"] == 2 and changed.json()["instructions"] == "Ton sérieux."
    # Only what is sent changes.
    assert changed.json()["name"] == "RH - congés"


async def test_a_run_keeps_the_assistant_and_version_that_made_it_when_the_assistant_changes_after(client):
    created = await make(client, instructions="Ton chaleureux.")
    run = (await run_with(client, created["id"])).json()
    await client.patch(f"/api/assistants/{created['id']}", json={"instructions": "Ton sérieux."})

    stored = await stored_run()

    assert run["assistant_id"] == created["id"] and run["assistant_version"] == 1
    assert run["assistant_name"] == "RH - congés"
    assert (stored.assistant_version, stored.assistant_instructions) == (1, "Ton chaleureux.")
    # Gone, the run still says what produced its answer.
    await client.delete(f"/api/assistants/{created['id']}")
    assert (await stored_run()).assistant_instructions == "Ton chaleureux."


async def test_the_messages_of_a_conversation_say_which_assistant_made_each_answer(client):
    created = await make(client, name="RH - congés")
    run = (await run_with(client, created["id"])).json()
    async with async_session_factory() as session:
        from app.models.message import MessageRole
        from app.repositories.conversation_repository import ConversationRepository

        await ConversationRepository(session).add_message(
            uuid.UUID(run["conversation_id"]), MessageRole.ASSISTANT, "Vingt-cinq jours.", run_id=uuid.UUID(run["id"])
        )
        await session.commit()
    await client.patch(f"/api/assistants/{created['id']}", json={"name": "Renommé"})

    messages = (await client.get(f"/api/conversations/{run['conversation_id']}/messages")).json()

    # As it was named when the answer was written.
    assert [message["assistant_name"] for message in messages] == [None, "RH - congés"]


# --- sharing ---


async def test_an_assistant_shared_by_email_reaches_that_person_when_they_log_in(client):
    created = await make(client)
    share = await share_with(client, created, email="Bob@Example.com")
    become(BOB)

    assert share["status"] == "pending" and "bob" not in share["display_hint"].replace("b***", "")
    assert (await client.get("/api/assistants")).json() == []  # not yet: nobody was looked up
    await logs_in(BOB, email="bob@example.com")
    listed = (await client.get("/api/assistants")).json()

    assert [a["id"] for a in listed] == [created["id"]]
    assert listed[0]["is_owner"] is False and listed[0]["can_edit"] is False


async def test_an_assistant_shared_with_a_group_reaches_its_members(client):
    created = await make(client)
    await share_with(client, created, group="/RH")
    await logs_in(BOB, groups=["/rh"])
    become(BOB, groups=["/rh"])
    in_group = (await client.get("/api/assistants")).json()
    become(CARL, groups=["/finance"])
    outside = (await client.get("/api/assistants")).json()

    assert [a["id"] for a in in_group] == [created["id"]] and outside == []


async def test_removing_a_share_takes_the_assistant_from_the_list_at_once_without_touching_a_run_going_on(client):
    created = await make(client)
    share = await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)
    run = await run_with(client, created["id"])
    become(ALICE)

    assert (await client.delete(f"/api/assistants/{created['id']}/shares/{share['id']}")).status_code == 204
    become(BOB)

    assert (await client.get("/api/assistants")).json() == []
    assert (await client.get(f"/api/assistants/{created['id']}")).status_code == 404
    assert (await run_with(client, created["id"])).status_code == 404
    # The run that was made is theirs and goes on.
    assert (await client.get(f"/api/runs/{run.json()['id']}")).status_code == 200


async def test_the_same_person_is_not_invited_twice(client):
    created = await make(client)
    await share_with(client, created, email="bob@example.com")

    again = await client.post(
        f"/api/assistants/{created['id']}/shares", json={"subject_type": "user", "identifier": "BOB@example.com"}
    )

    assert again.status_code == 409


async def test_only_the_author_shares_publishes_and_deletes_even_with_write_access(client):
    created = await make(client)
    share = await share_with(client, created, email="bob@example.com", permission="write")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)
    url = f"/api/assistants/{created['id']}"

    assert (
        await client.post(f"{url}/shares", json={"subject_type": "user", "identifier": "c@x.io"})
    ).status_code == 403
    assert (await client.get(f"{url}/shares")).status_code == 403
    assert (await client.patch(f"{url}/shares/{share['id']}", json={"permission": "read"})).status_code == 403
    assert (await client.put(f"{url}/visibility", json={"visibility": "public"})).status_code == 403
    assert (await client.delete(url)).status_code == 403


# --- who may change it ---


async def test_reading_lets_use_it_and_not_change_it_but_writing_does(client):
    created = await make(client, instructions="Ton chaleureux.")
    share = await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)
    url = f"/api/assistants/{created['id']}"

    assert (await client.patch(url, json={"name": "Le mien"})).status_code == 403
    become(ALICE)
    await client.patch(f"{url}/shares/{share['id']}", json={"permission": "write"})
    become(BOB)
    edited = await client.patch(url, json={"name": "Le nôtre"})

    assert edited.status_code == 200 and edited.json()["name"] == "Le nôtre" and edited.json()["can_edit"] is True
    assert edited.json()["is_owner"] is False


async def test_a_writer_who_saves_does_not_drop_the_collections_they_were_never_shown(client):
    open_one, hidden_one = await collection("Congés", public=True), await collection("Accords")
    created = await make(client, collection_ids=[str(open_one), str(hidden_one)])
    await share_with(client, created, email="bob@example.com", permission="write")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)
    url = f"/api/assistants/{created['id']}"

    seen = (await client.get(url)).json()
    saved = await client.patch(url, json={"collection_ids": [c["id"] for c in seen["collections"]], "name": "Nôtre"})

    assert seen["inaccessible_collection_count"] == 1 and saved.status_code == 200
    async with async_session_factory() as session:
        stored = (await session.execute(select(Assistant))).scalar_one()
    assert set(stored.collection_ids) == {str(open_one), str(hidden_one)}


# --- the rights: an assistant never opens a collection ---


async def test_a_recipient_without_access_to_a_collection_learns_nothing_of_it_and_the_run_does_not_search_it(client):
    conges, accords = await collection("Congés", public=True), await collection("Accords - confidentiel")
    created = await make(client, collection_ids=[str(conges), str(accords)])
    await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)

    listed = await client.get("/api/assistants")
    run = await run_with(client, created["id"])

    shown = listed.json()[0]
    assert shown["inaccessible_collection_count"] == 1
    assert [c["name"] for c in shown["collections"]] == ["Congés"]
    assert "Accords" not in listed.text and str(accords) not in listed.text
    assert run.status_code == 202 and run.json()["assistant_inaccessible_collections"] == 1
    stored = await stored_run()
    assert stored.pinned_collection_ids == [str(conges)] and stored.scope_locked is True
    assert "Accords" not in run.text and str(accords) not in run.text


async def test_an_assistant_none_of_whose_collections_can_be_read_does_not_search_everything_instead(client):
    accords = await collection("Accords")
    created = await make(client, collection_ids=[str(accords)])
    await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)

    response = await run_with(client, created["id"])

    assert response.status_code == 409
    async with async_session_factory() as session:
        assert (await session.execute(select(Run))).first() is None
        assert (await session.execute(select(Conversation))).first() is None


async def test_a_collection_deleted_after_leaves_the_assistant_working_with_the_others_and_says_so(client):
    one, two = await collection("Congés"), await collection("Accords")
    created = await make(client, collection_ids=[str(one), str(two)])
    async with async_session_factory() as session:
        await session.execute(delete(Collection).where(Collection.id == two))
        await session.commit()

    shown = (await client.get(f"/api/assistants/{created['id']}")).json()
    run = await run_with(client, created["id"])

    assert [c["name"] for c in shown["collections"]] == ["Congés"] and shown["inaccessible_collection_count"] == 1
    assert run.status_code == 202 and (await stored_run()).pinned_collection_ids == [str(one)]


async def test_an_assistant_without_collections_searches_what_the_person_may_read_as_usual(client):
    created = await make(client, instructions="Ton chaleureux.")

    await run_with(client, created["id"])
    stored = await stored_run()

    assert stored.pinned_collection_ids is None and stored.scope_locked is False
    assert stored.assistant_instructions == "Ton chaleureux."


async def test_the_chat_without_an_assistant_is_what_it_was(client):
    one = await collection("Congés")

    with patch("app.services.run_service.agent_runner.start"):
        await client.post("/api/runs", json={"query": "Q ?", "collection_ids": [str(one)]})
    stored = await stored_run()

    assert stored.pinned_collection_ids == [str(one)] and stored.scope_locked is False
    assert stored.assistant_id is None and stored.assistant_instructions is None


async def test_the_collections_picked_by_hand_are_replaced_by_the_assistants(client):
    designated, picked = await collection("Congés"), await collection("Autre")
    created = await make(client, collection_ids=[str(designated)])

    await run_with(client, created["id"], collection_ids=[str(picked)])

    assert (await stored_run()).pinned_collection_ids == [str(designated)]


async def test_the_web_search_is_only_on_when_the_assistant_allows_it_and_the_message_asks(client):
    refusing = await make(client, name="Sans web")
    allowing = await make(client, name="Avec web", web_search_allowed=True)

    await run_with(client, refusing["id"], web_search_enabled=True)
    await run_with(client, allowing["id"], web_search_enabled=True)
    await run_with(client, allowing["id"])

    async with async_session_factory() as session:
        runs = (await session.execute(select(Run).order_by(Run.created_at))).scalars().all()
    assert [run.web_search_enabled for run in runs] == [False, True, False]


# --- tools: the same graph, with some of them off ---


async def test_an_assistant_turns_off_some_optional_tools_and_its_runs_carry_them(client):
    created = await make(client, disabled_tools=["tabular_query", "time", "time"])

    assert created["disabled_tools"] == ["tabular_query", "time"]
    await run_with(client, created["id"])
    assert (await stored_run()).assistant_disabled_tools == ["tabular_query", "time"]


@pytest.mark.parametrize("tools", [["search"], ["web_search"], ["nope"]])
async def test_a_tool_that_is_required_or_unknown_cannot_be_turned_off(client, tools):
    response = await client.post("/api/assistants", json={"name": "RH", "disabled_tools": tools})

    assert response.status_code == 422


async def test_a_copy_keeps_the_tools_that_are_off_and_a_change_to_them_raises_the_version(client):
    created = await make(client, disabled_tools=["time"])
    changed = await client.patch(f"/api/assistants/{created['id']}", json={"disabled_tools": []})

    copy = await client.post(f"/api/assistants/{created['id']}/duplicate")

    assert changed.json()["version"] == 2 and changed.json()["disabled_tools"] == []
    assert copy.json()["disabled_tools"] == []


# --- instructions: who sees them ---


async def test_instructions_the_author_hides_apply_to_a_reader_without_being_shown(client):
    created = await make(client, instructions="Secret de fabrication.", hide_instructions=True)
    await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)

    shown = (await client.get(f"/api/assistants/{created['id']}")).json()
    await run_with(client, created["id"])

    assert shown["instructions"] is None and shown["instructions_hidden"] is True
    assert "Secret de fabrication" not in (await client.get("/api/assistants")).text
    assert (await stored_run()).assistant_instructions == "Secret de fabrication."


async def test_instructions_are_shown_to_a_reader_unless_hidden_and_always_to_a_writer(client):
    created = await make(client, instructions="Ton chaleureux.", hide_instructions=True)
    await share_with(client, created, email="bob@example.com", permission="write")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)

    assert (await client.get(f"/api/assistants/{created['id']}")).json()["instructions"] == "Ton chaleureux."


async def test_a_copy_of_an_assistant_with_hidden_instructions_gets_neither_them_nor_collections_it_cannot_read(client):
    open_one, hidden_one = await collection("Congés", public=True), await collection("Accords")
    created = await make(
        client, instructions="Secret.", hide_instructions=True, collection_ids=[str(open_one), str(hidden_one)]
    )
    await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)

    copy = await client.post(f"/api/assistants/{created['id']}/duplicate")

    assert copy.status_code == 201
    body = copy.json()
    assert body["is_owner"] and body["visibility"] == "private" and body["version"] == 1
    assert body["instructions"] == "" and body["name"] == "RH - congés (copie)"
    async with async_session_factory() as session:
        stored = (await session.execute(select(Assistant).where(Assistant.owner_id == BOB))).scalar_one()
    assert stored.collection_ids == [str(open_one)] and "Secret" not in stored.instructions


async def test_a_copy_gets_the_instructions_when_they_are_shown(client):
    created = await make(client, instructions="Ton chaleureux.")
    await share_with(client, created, email="bob@example.com")
    await logs_in(BOB, email="bob@example.com")
    become(BOB)

    copy = (await client.post(f"/api/assistants/{created['id']}/duplicate")).json()

    assert copy["instructions"] == "Ton chaleureux."


# --- public ---


async def test_making_an_assistant_public_needs_the_setting_or_an_administrator(client, monkeypatch):
    created = await make(client)
    url = f"/api/assistants/{created['id']}/visibility"

    assert (await client.put(url, json={"visibility": "public"})).status_code == 403
    monkeypatch.setattr(assistant_service._settings, "ASSISTANTS_PUBLIC_ENABLED", True)
    made = await client.put(url, json={"visibility": "public"})
    become(BOB)

    assert made.status_code == 200 and made.json()["visibility"] == "public"
    assert [a["id"] for a in (await client.get("/api/assistants")).json()] == [created["id"]]


async def test_an_administrator_takes_a_public_assistant_down_and_only_a_public_one(client, monkeypatch):
    monkeypatch.setattr(assistant_service._settings, "ASSISTANTS_PUBLIC_ENABLED", True)
    public, private = await make(client, name="Public"), await make(client, name="Privé")
    await client.put(f"/api/assistants/{public['id']}/visibility", json={"visibility": "public"})
    become(ADMIN, admin=True)

    assert (await client.delete(f"/api/assistants/{private['id']}")).status_code == 404
    assert (await client.delete(f"/api/assistants/{public['id']}")).status_code == 204
