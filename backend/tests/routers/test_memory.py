"""The memory of the assistant (#282, #283, #284): a person's own, never read for another, bounded, refusing what is
sensitive or what the guardrails refuse, off when they say so, and all an administrator sees of it is a count."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.guardrail import Enforcement, Guardrail, GuardrailType
from app.models.message import Message, MessageRole
from app.models.run import Run
from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory, UserMemorySettings
from app.schemas.run import RunCreate
from app.services import memory_service, run_service
from app.services.run_service import RunService
from tests.routers.test_tools import WORKER_KEY

ALICE, BOB, ROOT = "alice", "bob", "root"
HEADERS = {"X-API-Key": WORKER_KEY}


def become(user_id: str, *, admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=admin, groups=[]
    )


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        for model in (Run, Conversation, UserMemory, UserMemorySettings, Guardrail):
            await session.execute(delete(model))
        await session.commit()


async def remember(client, value: str, kind: str = "fact"):
    return await client.post("/api/memory/items", json={"kind": kind, "value": value})


async def make_run(user_id: str = ALICE, memory_mode: str = "on", assistant: bool = False) -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="t")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Bonjour")
        session.add(message)
        await session.flush()
        run = Run(
            user_id=user_id,
            message_id=message.id,
            conversation_id=conversation.id,
            query="Bonjour",
            user_groups=[],
            memory_mode=memory_mode,
            assistant_id=uuid.uuid4() if assistant else None,
        )
        session.add(run)
        await session.commit()
        return run.id


async def what_a_run_reads(client, run_id) -> dict:
    response = await client.get(f"/api/internal/runs/{run_id}/memory", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


async def command(client, run_id, action: str, text: str = "", kind: str = "fact") -> dict:
    response = await client.post(
        f"/api/internal/runs/{run_id}/memory/command",
        headers=HEADERS,
        json={"action": action, "text": text, "kind": kind},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- the person's own memory ---


async def test_what_i_ask_to_remember_is_mine_and_written_by_me(client):
    created = await remember(client, "Je préfère des réponses concises, en tableau", "preference")

    assert created.status_code == 201
    item = created.json()
    assert item["origin"] == "explicit" and item["kind"] == "preference" and item["confidence"] == 1
    overview = (await client.get("/api/memory")).json()
    assert overview["enabled"] is True and overview["available"] is True
    assert [i["value"] for i in overview["items"]] == ["Je préfère des réponses concises, en tableau"]


async def test_the_same_sentence_twice_is_one_item_not_two(client):
    first = await remember(client, "Je travaille à la DGFiP")
    second = await remember(client, "  je travaille à la  DGFIP ")

    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/api/memory")).json()["items"]) == 1
    assert second.json()["evidence_count"] == 2


async def test_nobody_reads_changes_or_deletes_the_memory_of_another(client):
    mine = (await remember(client, "Mon service est la DSI")).json()
    become(BOB)

    assert (await client.get("/api/memory")).json()["items"] == []
    assert (await client.patch(f"/api/memory/items/{mine['id']}", json={"value": "volé"})).status_code == 404
    assert (await client.delete(f"/api/memory/items/{mine['id']}")).status_code == 404
    assert (await client.delete("/api/memory/items")).status_code == 204
    become(ALICE)
    assert [i["value"] for i in (await client.get("/api/memory")).json()["items"]] == ["Mon service est la DSI"]


async def test_correcting_an_item_makes_it_mine_and_it_is_not_overwritten_by_what_is_learned(client):
    async with async_session_factory() as session:
        session.add(
            UserMemory(
                user_id=ALICE,
                kind=MemoryKind.PREFERENCE,
                key="style",
                value="Réponses longues",
                origin=MemoryOrigin.INFERRED,
                confidence=0.4,
            )
        )
        await session.commit()
        item_id = (await session.execute(select(UserMemory.id))).scalar_one()

    corrected = await client.patch(f"/api/memory/items/{item_id}", json={"value": "Réponses courtes"})

    assert corrected.status_code == 200
    assert corrected.json()["origin"] == "explicit" and corrected.json()["confidence"] == 1
    assert corrected.json()["value"] == "Réponses courtes"


async def test_an_item_can_be_turned_off_and_a_turned_off_item_is_not_read(client):
    item = (await remember(client, "Je réponds aux usagers")).json()
    run_id = await make_run()
    assert [i["value"] for i in (await what_a_run_reads(client, run_id))["items"]] == ["Je réponds aux usagers"]

    await client.patch(f"/api/memory/items/{item['id']}", json={"enabled": False})

    assert (await what_a_run_reads(client, run_id))["items"] == []
    assert len((await client.get("/api/memory")).json()["items"]) == 1


async def test_forgetting_one_item_or_everything(client):
    first = (await remember(client, "Je suis chargé de mission")).json()
    await remember(client, "Mon équipe est à Lyon")

    assert (await client.delete(f"/api/memory/items/{first['id']}")).status_code == 204
    assert len((await client.get("/api/memory")).json()["items"]) == 1
    assert (await client.delete("/api/memory/items")).status_code == 204
    assert (await client.get("/api/memory")).json()["items"] == []


async def test_the_export_has_everything_remembered_of_me_and_nothing_of_anyone_else(client):
    await remember(client, "Je préfère le vouvoiement", "preference")
    become(BOB)
    await remember(client, "Je suis à Nantes")
    become(ALICE)

    exported = (await client.get("/api/memory/export")).json()

    assert [i["value"] for i in exported["items"]] == ["Je préfère le vouvoiement"] and exported["enabled"] is True
    assert exported["exported_at"]


# --- what is never kept ---


@pytest.mark.parametrize(
    "value",
    [
        "J'ai un diabète de type 2",
        "Je suis enceinte",
        "Mon parti politique est le PS",
        "Je suis musulman pratiquant",
        "Mon orientation sexuelle est privée",
        "Je suis syndiqué à la CGT",
        "Ma santé est fragile",
    ],
)
async def test_nothing_sensitive_is_kept_even_when_i_ask_for_it(client, value):
    refused = await remember(client, value)

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "sensible"
    assert (await client.get("/api/memory")).json()["items"] == []


async def test_a_sensitive_correction_is_refused_too_and_the_item_is_left_as_it_was(client):
    item = (await remember(client, "Je travaille à Paris")).json()

    refused = await client.patch(f"/api/memory/items/{item['id']}", json={"value": "J'ai un cancer"})

    assert refused.status_code == 422
    assert (await client.get("/api/memory")).json()["items"][0]["value"] == "Je travaille à Paris"


async def test_a_sentence_is_one_line_and_not_too_long_and_not_empty(client, monkeypatch):
    assert (await remember(client, "   ")).json()["detail"]["code"] == "vide"
    assert (await remember(client, "x" * 301)).json()["detail"]["code"] == "trop_long"
    created = await remember(client, "Je lis\nle matin\t et le soir")
    assert created.json()["value"] == "Je lis le matin et le soir"


async def test_a_person_keeps_a_bounded_number_of_items(client, monkeypatch):
    monkeypatch.setattr(memory_service._settings, "MEMORY_MAX_ITEMS", 2)
    await remember(client, "Premier")
    await remember(client, "Deuxième")

    full = await remember(client, "Troisième")

    assert full.status_code == 422 and full.json()["detail"]["code"] == "limite"
    # Saying again what is there is not adding.
    assert (await remember(client, "Premier")).status_code == 200


async def test_what_the_guardrails_refuse_in_a_message_is_not_kept_in_the_memory(client):
    async with async_session_factory() as session:
        session.add(
            Guardrail(
                name="Pas d'IBAN",
                type=GuardrailType.RULES,
                config={"builtins": ["iban"]},
                enabled=True,
                enforcement=Enforcement.BLOCK,
                refusal_message="Pas de coordonnées bancaires.",
            )
        )
        await session.commit()

    refused = await remember(client, "Mon IBAN est FR76 3000 6000 0112 3456 7890 189")

    assert refused.status_code == 422 and refused.json()["detail"]["message"] == "Pas de coordonnées bancaires."
    assert (await client.get("/api/memory")).json()["items"] == []


# --- off ---


async def test_with_my_memory_off_nothing_is_read_and_the_data_stays(client):
    await remember(client, "Je suis analyste")
    run_id = await make_run()

    await client.put("/api/memory/settings", json={"enabled": False})

    read = await what_a_run_reads(client, run_id)
    assert read == {"state": "disabled", "items": [], "habits": []}
    assert len((await client.get("/api/memory")).json()["items"]) == 1
    assert (await client.get("/api/memory")).json()["enabled"] is False
    await client.put("/api/memory/settings", json={"enabled": True})
    assert (await what_a_run_reads(client, run_id))["state"] == "on"


async def test_the_administrator_can_suspend_the_memory_everywhere(client, monkeypatch):
    await remember(client, "Je suis analyste")
    run_id = await make_run()
    monkeypatch.setattr(memory_service._settings, "MEMORY_ENABLED", False)

    assert await what_a_run_reads(client, run_id) == {"state": "suspended", "items": [], "habits": []}
    assert (await client.get("/api/memory")).json()["available"] is False
    refused = await command(client, run_id, "remember", "Je suis analyste")
    assert refused["outcome"] == "suspended"


@pytest.mark.parametrize("mode, assistant", [("temporary", False), ("unavailable", False), ("on", False)])
async def test_a_run_reads_the_memory_only_in_the_personal_chat_that_keeps_it_on(client, mode, assistant):
    await remember(client, "Je suis analyste")
    run_id = await make_run(memory_mode=mode, assistant=assistant)

    read = await what_a_run_reads(client, run_id)

    assert read["state"] == mode
    assert bool(read["items"]) is (mode == "on")


async def test_the_memory_read_for_a_run_is_the_one_of_its_person_and_fits_the_prompt(client, monkeypatch):
    await remember(client, "Je préfère les tableaux")
    become(BOB)
    await remember(client, "Je suis à Nantes")
    become(ALICE)
    monkeypatch.setattr(memory_service._settings, "MEMORY_PROMPT_MAX_CHARS", 30)
    await remember(client, "Une autre phrase assez longue pour déborder")
    run_id = await make_run(ALICE)

    values = [i["value"] for i in (await what_a_run_reads(client, run_id))["items"]]

    assert values == ["Je préfère les tableaux"]


async def test_a_run_that_does_not_exist_has_no_memory_to_read(client):
    response = await client.get(f"/api/internal/runs/{uuid.uuid4()}/memory", headers=HEADERS)

    assert response.status_code == 404


async def test_the_memory_is_not_read_without_the_key_of_the_workers(client):
    assert (await client.get(f"/api/internal/runs/{uuid.uuid4()}/memory")).status_code in (401, 403)


async def test_the_use_of_the_memory_is_counted_on_the_run_and_dated_on_the_items(client):
    item = (await remember(client, "Je préfère les tableaux")).json()
    run_id = await make_run()

    done = await client.post(f"/api/internal/runs/{run_id}/memory/used", headers=HEADERS, json={"ids": [item["id"]]})

    assert done.status_code == 204
    async with async_session_factory() as session:
        assert (await session.get(Run, run_id)).memory_used == 1
        assert (await session.get(UserMemory, uuid.UUID(item["id"]))).last_used_at is not None


# --- in the chat ---


async def test_asked_in_the_chat_to_remember_the_assistant_keeps_it_and_says_so(client):
    run_id = await make_run()

    said = await command(client, run_id, "remember", "Je préfère les réponses en tableau", "preference")

    assert said["outcome"] == "saved" and "Je préfère les réponses en tableau" in said["message"]
    item = (await client.get("/api/memory")).json()["items"][0]
    assert item["origin"] == "explicit" and item["kind"] == "preference"


async def test_asked_in_the_chat_to_remember_something_sensitive_it_refuses_and_keeps_nothing(client):
    run_id = await make_run()

    said = await command(client, run_id, "remember", "J'ai un cancer")

    assert said["outcome"] == "refused" and "ne retiens rien" in said["message"]
    assert (await client.get("/api/memory")).json()["items"] == []


async def test_asked_in_the_chat_to_forget_it_forgets_one_item_and_never_guesses_among_several(client):
    await remember(client, "Mon équipe est à Lyon")
    await remember(client, "Mon service est à Lyon")
    await remember(client, "Je préfère les tableaux")
    run_id = await make_run()

    several = await command(client, run_id, "forget", "Lyon")
    one = await command(client, run_id, "forget", "tableaux")
    none = await command(client, run_id, "forget", "Marseille")

    assert several["outcome"] == "several" and "Mon équipe est à Lyon" in several["message"]
    assert one["outcome"] == "deleted" and none["outcome"] == "not_found"
    assert len((await client.get("/api/memory")).json()["items"]) == 2


async def test_asked_in_the_chat_what_it_knows_the_assistant_lists_it_by_kind(client):
    run_id = await make_run()
    assert "rien" in (await command(client, run_id, "show"))["message"]
    await remember(client, "Je préfère les tableaux", "preference")
    await remember(client, "Je suis chargé de mission", "context")

    said = (await command(client, run_id, "show"))["message"]

    assert "**Préférences**" in said and "- Je préfère les tableaux" in said and "**Contexte**" in said


@pytest.mark.parametrize("mode", ["temporary", "unavailable"])
async def test_asked_in_a_chat_without_memory_the_assistant_says_why_and_keeps_nothing(client, mode):
    run_id = await make_run(memory_mode=mode)

    said = await command(client, run_id, "remember", "Je suis analyste")

    assert said["outcome"] == mode
    assert (await client.get("/api/memory")).json()["items"] == []


async def test_asked_to_remember_with_the_memory_off_the_assistant_says_how_to_turn_it_on(client):
    await client.put("/api/memory/settings", json={"enabled": False})
    run_id = await make_run()

    said = await command(client, run_id, "remember", "Je suis analyste")

    assert said["outcome"] == "disabled" and "Ma mémoire" in said["message"]
    assert (await client.get("/api/memory")).json()["items"] == []


async def test_a_command_is_for_the_person_of_the_run(client):
    run_id = await make_run(BOB)

    await command(client, run_id, "remember", "Je suis à Nantes")

    assert (await client.get("/api/memory")).json()["items"] == []
    async with async_session_factory() as session:
        assert [m.user_id for m in (await session.execute(select(UserMemory))).scalars()] == [BOB]


# --- what an administrator sees ---


async def test_an_administrator_sees_counts_and_never_what_is_remembered(client):
    await remember(client, "Je suis analyste")
    await client.put("/api/memory/settings", json={"enabled": False})

    assert (await client.get("/api/admin/memory/stats")).status_code == 403
    become(ROOT, admin=True)
    stats = (await client.get("/api/admin/memory/stats")).json()

    assert stats == {"available": True, "people": 1, "items": 1, "turned_off": 1}
    assert (await client.get("/api/memory")).json()["items"] == []


# --- when a run uses it ---


async def mode_of_new_run(client, monkeypatch, **body) -> str:
    monkeypatch.setattr(run_service.agent_runner, "start", lambda *args, **kwargs: None)
    response = await client.post("/api/runs", json={"query": "Bonjour", **body})
    assert response.status_code == 202, response.text
    async with async_session_factory() as session:
        return (await session.get(Run, uuid.UUID(response.json()["id"]))).memory_mode


async def test_a_message_uses_the_memory_unless_the_conversation_was_started_without_it(client, monkeypatch):
    assert await mode_of_new_run(client, monkeypatch) == "on"
    assert await mode_of_new_run(client, monkeypatch, use_memory=False) == "temporary"


async def test_a_run_started_by_a_routine_or_by_the_api_never_uses_the_memory(client, monkeypatch):
    monkeypatch.setattr(run_service.agent_runner, "start", lambda *args, **kwargs: None)
    user = RequestContext(user_id=ALICE, email="a@example.com", roles=[], is_admin=False, groups=[])
    async with async_session_factory() as session:
        routine = await RunService(session).create_run(user, RunCreate(query="Quoi de neuf ?"), automated=True)
        api = await RunService(session).create_run(user, RunCreate(query="Bonjour"), scope_locked=True)
    async with async_session_factory() as session:
        modes = [(await session.get(Run, out.id)).memory_mode for out in (routine, api)]

    assert modes == ["unavailable", "unavailable"]
