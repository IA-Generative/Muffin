"""The collections a person uses most (#286): counted from what their answers cited and what they attached, a habit only
from a second use, forgotten as it fades or when the person can no longer read the collection, never proposed unless
readable, and left alone when the person wrote it or their memory is not in use."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import habits
from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionVisibility
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.run import Run
from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory, UserMemorySettings
from app.services import habit_service, memory_service
from app.services.habit_service import HabitService
from tests.routers.test_memory import ALICE, BOB, HEADERS, become
from tests.routers.test_tools import WORKER_KEY


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        for model in (Run, Conversation, UserMemory, UserMemorySettings, Collection):
            await session.execute(delete(model))
        await session.commit()


async def collection(name: str = "Règlements", owner: str = "owner", public: bool = True) -> uuid.UUID:
    async with async_session_factory() as session:
        row = Collection(
            owner_id=owner,
            name=name,
            visibility=CollectionVisibility.PUBLIC if public else CollectionVisibility.PRIVATE,
        )
        session.add(row)
        await session.commit()
        return row.id


def cite(*ids: uuid.UUID, cited: bool = True) -> list[dict]:
    return [{"tool": "search", "vdb_id": str(cid), "cited": cited, "content": "x"} for cid in ids]


async def answer(
    user_id: str = ALICE,
    cites: list[uuid.UUID] | None = None,
    pinned: list[uuid.UUID] | None = None,
    memory_mode: str = "on",
    guardrail: str | None = None,
    citations: list[dict] | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """A run that has ended, as the chat leaves it, and counted - as the result route does once the answer is kept."""
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="t")
        session.add(conversation)
        await session.flush()
        question = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Question")
        session.add(question)
        await session.flush()
        run = Run(
            user_id=user_id,
            message_id=question.id,
            conversation_id=conversation.id,
            query="Question",
            user_groups=[],
            memory_mode=memory_mode,
            guardrail_outcome=guardrail,
            citations=citations if citations is not None else cite(*(cites or [])),
            pinned_collection_ids=[str(c) for c in pinned or []] or None,
        )
        if created_at is not None:
            run.created_at = created_at
        session.add(run)
        await session.commit()
        run_id = run.id
    async with async_session_factory() as session:
        await HabitService(session).record_run(run_id)
    return run_id


async def used(collection_id: uuid.UUID, times: int, **kwargs) -> None:
    for _ in range(times):
        await answer(cites=[collection_id], **kwargs)


async def shown(client) -> list[dict]:
    return [i for i in (await client.get("/api/memory")).json()["items"] if i["kind"] == "habit"]


async def proposed(client) -> list[str]:
    return (await client.get("/api/memory/habits")).json()["collection_ids"]


async def read_by_a_run(client, user_id: str = ALICE) -> dict:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="t")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Question")
        session.add(message)
        await session.flush()
        run = Run(user_id=user_id, message_id=message.id, conversation_id=conversation.id, query="Q", user_groups=[])
        session.add(run)
        await session.commit()
        run_id = run.id
    return (await client.get(f"/api/internal/runs/{run_id}/memory", headers=HEADERS)).json()


async def rows() -> list[UserMemory]:
    async with async_session_factory() as session:
        return list((await session.execute(select(UserMemory))).scalars())


# --- what makes a habit ---


async def test_a_collection_an_answer_cited_is_not_a_habit_until_a_second_use(client):
    reglements = await collection()

    await used(reglements, 1)
    assert await shown(client) == [] and await proposed(client) == []

    await used(reglements, 1)
    [item] = await shown(client)

    assert item["value"] == "Consulte souvent la collection « Règlements »"
    assert item["origin"] == "inferred" and item["kind"] == "habit"
    assert await proposed(client) == [str(reglements)]


async def test_a_collection_the_person_attached_counts_half_and_only_for_an_answer_that_rests_on_something(client):
    reglements = await collection()
    # An answer that cited something - here a collection the person cannot read, which counts for nothing itself.
    unreadable = await collection("Secrète", owner="someone", public=False)
    for _ in range(3):
        await answer(cites=[unreadable], pinned=[reglements])
    # Three attachments make 1.5: not yet.
    assert await shown(client) == []

    await answer(cites=[unreadable], pinned=[reglements])

    assert await proposed(client) == [str(reglements)]
    # Nothing was cited: attaching says nothing of what the person uses.
    nothing = await collection("Rien")
    for _ in range(6):
        await answer(pinned=[nothing], citations=[])
    assert str(nothing) not in await proposed(client)


async def test_a_citation_that_is_only_consulted_and_not_cited_does_not_count(client):
    reglements = await collection()

    for _ in range(3):
        await answer(citations=cite(reglements, cited=False))

    assert await shown(client) == []


async def test_the_most_used_comes_first(client):
    seldom, often = await collection("Rare"), await collection("Fréquente")
    await used(seldom, 2)
    await used(often, 4)

    assert await proposed(client) == [str(often), str(seldom)]


async def test_what_the_routing_reads_is_a_weight_and_never_a_sentence_for_a_model(client):
    reglements = await collection()
    await used(reglements, 3)

    memory = await read_by_a_run(client)

    assert memory["items"] == []
    [habit] = memory["habits"]
    assert habit["collection_id"] == str(reglements) and 0 < habit["weight"] <= 1


async def test_a_run_of_another_person_counts_for_nobody_but_them(client):
    reglements = await collection()
    await used(reglements, 3, user_id=BOB)

    assert await shown(client) == [] and await proposed(client) == []
    become(BOB)
    assert await proposed(client) == [str(reglements)]


# --- never what is not readable ---


async def test_a_collection_the_person_cannot_read_is_never_counted_nor_proposed(client):
    secret = await collection("Secrète", owner="someone", public=False)

    await used(secret, 4)

    assert await shown(client) == [] and await proposed(client) == [] and await rows() == []


async def test_a_collection_whose_access_was_removed_is_forgotten_and_never_proposed(client):
    reglements = await collection(owner="someone", public=True)
    await used(reglements, 3)
    assert await proposed(client) == [str(reglements)]
    async with async_session_factory() as session:
        (await session.get(Collection, reglements)).visibility = CollectionVisibility.PRIVATE
        await session.commit()

    assert await proposed(client) == [] and await shown(client) == [] and await rows() == []
    assert (await read_by_a_run(client))["habits"] == []


async def test_a_deleted_collection_is_forgotten(client):
    reglements = await collection()
    await used(reglements, 3)
    async with async_session_factory() as session:
        await session.execute(delete(Collection).where(Collection.id == reglements))
        await session.commit()

    assert await shown(client) == [] and await rows() == []


async def test_a_renamed_collection_is_named_as_it_is_today(client):
    reglements = await collection("Règlements")
    await used(reglements, 3)
    async with async_session_factory() as session:
        (await session.get(Collection, reglements)).name = "Règlements 2026"
        await session.commit()

    assert [i["value"] for i in await shown(client)] == ["Consulte souvent la collection « Règlements 2026 »"]


async def test_the_temporary_collection_of_a_conversation_is_never_a_habit(client):
    async with async_session_factory() as session:
        conversation = Conversation(user_id=ALICE, title="t")
        session.add(conversation)
        await session.flush()
        row = Collection(
            owner_id=ALICE,
            name="Fichiers de la conversation",
            visibility=CollectionVisibility.PRIVATE,
            is_temporary=True,
            conversation_id=conversation.id,
        )
        session.add(row)
        await session.commit()
        temporary = row.id

    await used(temporary, 4)

    assert await rows() == []


# --- it fades ---


async def test_a_habit_fades_with_time_and_is_no_longer_one(client):
    reglements = await collection()
    await used(reglements, 3)
    async with async_session_factory() as session:
        item = (await session.execute(select(UserMemory))).scalar_one()
        item.data = {**item.data, "at": (datetime.now(UTC) - timedelta(days=45)).isoformat()}
        await session.commit()

    assert await shown(client) == [] and await proposed(client) == []
    assert len(await rows()) == 1


async def test_what_has_faded_away_is_forgotten_at_the_next_use_of_anything(client):
    old, fresh = await collection("Ancienne"), await collection("Récente")
    await used(old, 3)
    async with async_session_factory() as session:
        item = (await session.execute(select(UserMemory))).scalar_one()
        item.data = {**item.data, "at": (datetime.now(UTC) - timedelta(days=200)).isoformat()}
        await session.commit()

    await used(fresh, 1)

    assert [r.data["collection_id"] for r in await rows()] == [str(fresh)]


async def test_no_more_than_the_limit_are_kept_the_ones_that_weigh_most(client, monkeypatch):
    monkeypatch.setattr(habit_service._settings, "MEMORY_HABITS_MAX", 2)
    first, second, third = await collection("A"), await collection("B"), await collection("C")
    await used(first, 5)
    await used(second, 3)
    await used(third, 2)

    assert {r.data["collection_id"] for r in await rows()} == {str(first), str(second)}


# --- whose it is ---


async def test_a_habit_the_person_wrote_is_never_overwritten(client):
    reglements = await collection()
    async with async_session_factory() as session:
        session.add(
            UserMemory(
                user_id=ALICE,
                kind=MemoryKind.HABIT,
                key=habits.key_of(reglements),
                value="Ma collection de référence",
                origin=MemoryOrigin.EXPLICIT,
                data={"collection_id": str(reglements), "score": 9, "at": datetime.now(UTC).isoformat()},
            )
        )
        await session.commit()

    await used(reglements, 3)

    [row] = await rows()
    assert row.value == "Ma collection de référence" and row.origin == MemoryOrigin.EXPLICIT and row.data["score"] == 9


async def test_a_habit_turned_off_is_not_used_by_the_routing_nor_proposed(client):
    reglements = await collection()
    await used(reglements, 3)
    [item] = await shown(client)

    await client.patch(f"/api/memory/items/{item['id']}", json={"enabled": False})

    assert await proposed(client) == [] and (await read_by_a_run(client))["habits"] == []
    assert len(await shown(client)) == 1


async def test_a_habit_the_person_removed_needs_new_uses_to_come_back(client):
    reglements = await collection()
    await used(reglements, 3)
    [item] = await shown(client)
    assert (await client.delete(f"/api/memory/items/{item['id']}")).status_code == 204

    await used(reglements, 1)
    assert await shown(client) == []
    await used(reglements, 1)

    assert len(await shown(client)) == 1


async def test_what_was_used_before_the_person_removed_a_habit_is_not_counted_afterwards(client):
    reglements = await collection()
    old = await answer(cites=[reglements])
    await used(reglements, 2)
    [item] = await shown(client)
    await client.delete(f"/api/memory/items/{item['id']}")

    async with async_session_factory() as session:
        await HabitService(session).record_run(old)

    assert await rows() == []


# --- when nothing is counted ---


@pytest.mark.parametrize("mode", ["temporary", "unavailable"])
async def test_nothing_is_counted_where_the_memory_was_not_in_use(client, mode):
    await used(await collection(), 4, memory_mode=mode)

    assert await rows() == []


async def test_nothing_is_counted_for_a_request_the_guardrails_stopped(client):
    await used(await collection(), 4, guardrail="blocked")

    assert await rows() == []


async def test_nothing_is_counted_with_the_memory_off_or_suspended_or_the_learning_off(client, monkeypatch):
    reglements = await collection()
    await client.put("/api/memory/settings", json={"enabled": False})
    await used(reglements, 3)
    assert await rows() == []
    assert await proposed(client) == []

    await client.put("/api/memory/settings", json={"enabled": True})
    monkeypatch.setattr(habit_service._settings, "MEMORY_LEARNING_ENABLED", False)
    await used(reglements, 3)
    assert await rows() == []

    monkeypatch.setattr(habit_service._settings, "MEMORY_LEARNING_ENABLED", True)
    await used(reglements, 3)
    monkeypatch.setattr(habit_service._settings, "MEMORY_ENABLED", False)
    assert await proposed(client) == []


async def test_turning_the_memory_off_stops_the_use_of_the_habits_and_keeps_them(client):
    reglements = await collection()
    await used(reglements, 3)

    await client.put("/api/memory/settings", json={"enabled": False})

    assert await proposed(client) == [] and (await read_by_a_run(client))["habits"] == []
    await client.put("/api/memory/settings", json={"enabled": True})
    assert await proposed(client) == [str(reglements)]


# --- how it is reached ---


async def test_the_result_route_counts_what_the_answer_used_and_a_failure_never_fails_it(client, monkeypatch):
    reglements = await collection()

    async def finish() -> uuid.UUID:
        async with async_session_factory() as session:
            conversation = Conversation(user_id=ALICE, title="t")
            session.add(conversation)
            await session.flush()
            question = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Question")
            session.add(question)
            await session.flush()
            run = Run(user_id=ALICE, message_id=question.id, conversation_id=conversation.id, query="Q", user_groups=[])
            session.add(run)
            await session.commit()
            run_id = run.id
        response = await client.patch(
            f"/api/internal/runs/{run_id}/result",
            headers=HEADERS,
            json={"answer": "Réponse", "citations": cite(reglements)},
        )
        assert response.status_code == 200, response.text
        return run_id

    await finish()
    assert await shown(client) == []
    await finish()
    assert len(await shown(client)) == 1

    async def broken(self, run_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(HabitService, "_record_run", broken)
    await finish()


async def test_the_export_and_the_chat_show_only_the_habits_that_are_one(client):
    reglements, once = await collection(), await collection("Une fois")
    await used(reglements, 3)
    await used(once, 1)

    exported = (await client.get("/api/memory/export")).json()["items"]

    assert [i["value"] for i in exported] == ["Consulte souvent la collection « Règlements »"]
    assert memory_service.available() is True
