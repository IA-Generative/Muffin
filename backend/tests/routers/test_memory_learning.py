"""What the assistant learns of the style a person likes from their 👍/👎 (#285): in place before their next question,
never from one vote, never over what they wrote, never when their memory is not in use, and not back once removed."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core import style_signals
from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.feedback import Feedback, FeedbackValue
from app.models.message import Message, MessageRole
from app.models.run import Run
from app.models.user_memory import MemoryKind, MemoryOrigin, UserMemory, UserMemorySettings
from app.services import memory_learning_service, memory_service
from tests.routers.test_memory import ALICE, BOB, HEADERS, become
from tests.routers.test_tools import WORKER_KEY

CONCISE = "Préfère des réponses concises"
DETAILED = "Préfère des réponses détaillées"
NO_TABLE = "Préfère éviter les tableaux"


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_KEY)
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        for model in (Feedback, Run, Conversation, UserMemory, UserMemorySettings):
            await session.execute(delete(model))
        await session.commit()


async def answered(user_id: str = ALICE, text: str = "x" * 1000, memory_mode: str = "on") -> uuid.UUID:
    """A question and its answer, as the chat leaves them. Returns the run to give feedback on."""
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
        )
        session.add(run)
        await session.flush()
        session.add(Message(conversation_id=conversation.id, role=MessageRole.ASSISTANT, content=text, run_id=run.id))
        await session.commit()
        return run.id


async def rate(client, run_id, value: str = "down", comment: str | None = None, reasons: list[str] | None = None):
    response = await client.post(
        f"/api/runs/{run_id}/feedback", json={"value": value, "comment": comment, "reasons": reasons or []}
    )
    assert response.status_code in (200, 201), response.text
    return response


async def what_i_remember(client) -> list[dict]:
    return (await client.get("/api/memory")).json()["items"]


async def what_a_run_reads(client, run_id) -> list[str]:
    response = await client.get(f"/api/internal/runs/{run_id}/memory", headers=HEADERS)
    return [item["value"] for item in response.json()["items"]]


async def too_long(client, count: int, user_id: str = ALICE):
    runs = [await answered(user_id) for _ in range(count)]
    for run_id in runs:
        await rate(client, run_id, comment="Trop long")
    return runs


# --- what is learned, and when ---


async def test_two_thumbs_down_for_being_too_long_make_a_preference_that_the_next_question_already_has(client):
    await too_long(client, 2)
    next_run = await answered()

    items = await what_i_remember(client)

    assert [(i["value"], i["origin"], i["kind"]) for i in items] == [(CONCISE, "inferred", "preference")]
    assert items[0]["confidence"] > 0 and items[0]["evidence_count"] == 2
    assert await what_a_run_reads(client, next_run) == [CONCISE]


async def test_one_single_thumb_down_settles_nothing(client):
    await too_long(client, 1)

    assert await what_i_remember(client) == []


async def test_a_word_and_two_measures_agree_enough_but_two_measures_alone_do_not(client):
    await rate(client, await answered(text="Oui."), "up")
    await rate(client, await answered(text="Non."), "up")
    assert await what_i_remember(client) == []

    await rate(client, await answered(), comment="Un peu trop long")

    assert [i["value"] for i in await what_i_remember(client)] == [CONCISE]


async def test_thumbs_down_for_the_tone_the_facts_or_the_sources_teach_no_style(client):
    for reason in ("inappropriate_tone", "incorrect_answer", "questionable_sources", "other"):
        for _ in range(2):
            await rate(client, await answered(text="x" * 3000), reasons=[reason])

    assert await what_i_remember(client) == []


async def test_tables_are_learned_from_what_is_said(client):
    for _ in range(2):
        await rate(client, await answered(), comment="Pas de tableau, s'il te plaît")

    assert [i["value"] for i in await what_i_remember(client)] == [NO_TABLE]


async def test_the_words_of_a_comment_are_never_kept_only_the_sentence_of_the_preference(client):
    for _ in range(2):
        await rate(client, await answered(), comment="Trop long, madame Dupont a le même avis que moi")

    items = await what_i_remember(client)
    allowed = {sentence for _, sentence in style_signals.LEARNED.values()}

    assert [i["value"] for i in items] and {i["value"] for i in items} <= allowed
    assert "Dupont" not in str(items)


# --- it does not overstate ---


async def test_a_contradiction_cancels_what_was_learned(client):
    await too_long(client, 2)
    assert [i["value"] for i in await what_i_remember(client)] == [CONCISE]

    for _ in range(3):
        await rate(client, await answered(), comment="Trop court")

    assert await what_i_remember(client) == []


async def test_enough_that_agree_the_other_way_turn_it_round(client):
    await too_long(client, 2)

    for _ in range(4):
        await rate(client, await answered(), comment="Pas assez détaillé")

    assert [i["value"] for i in await what_i_remember(client)] == [DETAILED]


async def test_changing_ones_mind_replaces_the_old_feedback_it_does_not_add_to_it(client):
    runs = await too_long(client, 2)
    assert [i["value"] for i in await what_i_remember(client)] == [CONCISE]

    await rate(client, runs[0], "up")

    assert await what_i_remember(client) == []


async def test_a_signal_fades_with_time_and_what_is_too_old_is_not_looked_at(client):
    runs = await too_long(client, 2)
    async with async_session_factory() as session:
        for feedback in (await session.execute(select(Feedback))).scalars():
            feedback.created_at = datetime.now(UTC) - timedelta(days=60)
        await session.commit()

    await rate(client, await answered(), "up")

    assert runs and await what_i_remember(client) == []


async def test_what_a_learned_item_was_worth_is_kept_for_a_while_only(client):
    await too_long(client, 2)
    next_run = await answered()
    async with async_session_factory() as session:
        item = (await session.execute(select(UserMemory))).scalar_one()
        assert item.expires_at is not None and item.expires_at > datetime.now(UTC) + timedelta(days=30)
        item.expires_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()

    assert await what_a_run_reads(client, next_run) == []
    assert len(await what_i_remember(client)) == 1


# --- whose it is ---


async def test_what_i_wrote_is_never_overwritten_by_what_is_learned(client):
    async with async_session_factory() as session:
        session.add(
            UserMemory(
                user_id=ALICE,
                kind=MemoryKind.PREFERENCE,
                key="appris-verbosite",
                value="Réponses longues et complètes",
                origin=MemoryOrigin.EXPLICIT,
            )
        )
        await session.commit()

    await too_long(client, 3)

    assert [(i["value"], i["origin"]) for i in await what_i_remember(client)] == [
        ("Réponses longues et complètes", "explicit")
    ]


async def test_the_feedback_of_another_person_teaches_me_nothing(client):
    become(BOB)
    await too_long(client, 3, user_id=BOB)
    become(ALICE)

    assert await what_i_remember(client) == []
    become(BOB)
    assert [i["value"] for i in await what_i_remember(client)] == [CONCISE]


async def test_a_learned_item_the_person_turns_off_stays_off_when_it_is_learned_again(client):
    await too_long(client, 2)
    item = (await what_i_remember(client))[0]
    await client.patch(f"/api/memory/items/{item['id']}", json={"enabled": False})

    await too_long(client, 1)

    [again] = await what_i_remember(client)
    assert again["id"] == item["id"] and again["enabled"] is False


async def test_what_the_person_removed_does_not_come_back_with_the_next_thumb(client):
    await too_long(client, 2)
    [item] = await what_i_remember(client)
    assert (await client.delete(f"/api/memory/items/{item['id']}")).status_code == 204

    await too_long(client, 1)
    assert await what_i_remember(client) == []
    await too_long(client, 1)

    assert [i["value"] for i in await what_i_remember(client)] == [CONCISE]


async def test_deleting_everything_forgets_what_had_been_learned_from_too(client):
    await too_long(client, 2)
    await client.delete("/api/memory/items")

    await too_long(client, 1)

    assert await what_i_remember(client) == []


# --- when nothing is learned ---


async def test_nothing_is_learned_with_the_memory_off(client):
    await client.put("/api/memory/settings", json={"enabled": False})

    await too_long(client, 3)

    assert await what_i_remember(client) == []


@pytest.mark.parametrize("mode", ["temporary", "unavailable"])
async def test_nothing_is_learned_from_a_conversation_where_the_memory_was_not_in_use(client, mode):
    for _ in range(3):
        await rate(client, await answered(memory_mode=mode), comment="Trop long")

    assert await what_i_remember(client) == []


async def test_learning_can_be_switched_off_and_the_memory_suspended(client, monkeypatch):
    monkeypatch.setattr(memory_learning_service._settings, "MEMORY_LEARNING_ENABLED", False)
    await too_long(client, 2)
    assert await what_i_remember(client) == []

    monkeypatch.setattr(memory_learning_service._settings, "MEMORY_LEARNING_ENABLED", True)
    monkeypatch.setattr(memory_learning_service._settings, "MEMORY_ENABLED", False)
    await too_long(client, 2)

    assert await what_i_remember(client) == []


async def test_a_learned_item_counts_in_the_limit_and_is_not_added_beyond_it(client, monkeypatch):
    monkeypatch.setattr(memory_service._settings, "MEMORY_MAX_ITEMS", 1)
    monkeypatch.setattr(memory_learning_service._settings, "MEMORY_MAX_ITEMS", 1)
    await client.post("/api/memory/items", json={"kind": "fact", "value": "Je suis analyste"})

    await too_long(client, 2)

    assert [i["value"] for i in await what_i_remember(client)] == ["Je suis analyste"]


# --- the feedback comes first ---


async def test_a_failure_to_learn_never_fails_the_feedback_that_is_kept(client, monkeypatch):
    async def broken(self, user_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(memory_learning_service.MemoryLearningService, "_learn", broken)
    run_id = await answered()

    response = await rate(client, run_id, comment="Trop long")

    assert response.json()["value"] == FeedbackValue.DOWN.value
    async with async_session_factory() as session:
        assert len((await session.execute(select(Feedback))).scalars().all()) == 1
