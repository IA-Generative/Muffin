"""What a routine does when it is due (#524): one run per date even with several replicas, in the name of the person
with the rights they have then and no administrator's, no tool of their token; the reasons for not running; the
failures that put a routine aside; and a notification that never carries an answer."""
# ruff: noqa: F811 - the fixtures of the routine tests are imported, and used by name

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.agent.runner import agent_runner
from app.db import async_session_factory
from app.models.collection import Collection, CollectionVisibility
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.message import Message
from app.models.notification import Notification
from app.models.routine import Routine, RoutineRun, RoutineRunStatus, RoutineSettings
from app.models.run import Run, RunStatus
from app.models.token_usage import TokenUsage, TokenUsageKind, UserProfile
from app.services.routine_runner import routine_scheduler
from tests.routers.test_routines import (  # noqa: F401
    ALICE,
    BOB,
    ROOT,
    become,
    body,
    client,
    collection,
    enable,
    load,
    make,
)


async def make_due(routine_id: str, minutes: int = 1) -> None:
    async with async_session_factory() as session:
        await session.execute(
            update(Routine)
            .where(Routine.id == uuid.UUID(routine_id))
            .values(next_run_at=datetime.now(UTC) - timedelta(minutes=minutes))
        )
        await session.commit()


async def history(routine_id: str) -> list[RoutineRun]:
    async with async_session_factory() as session:
        rows = await session.execute(
            select(RoutineRun)
            .where(RoutineRun.routine_id == uuid.UUID(routine_id))
            .order_by(RoutineRun.started_at, RoutineRun.id)
        )
        return list(rows.scalars())


async def runs_of(user_id: str) -> list[Run]:
    async with async_session_factory() as session:
        return list((await session.execute(select(Run).where(Run.user_id == user_id))).scalars())


async def notifications_of(user_id: str) -> list[Notification]:
    async with async_session_factory() as session:
        rows = await session.execute(
            select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at)
        )
        return list(rows.scalars())


async def end(routine_id: str, status: RunStatus = RunStatus.COMPLETED, tokens: int = 0) -> RoutineRun:
    """The agent ended its run: what follows the run records it."""
    [*_, entry] = await history(routine_id)
    if tokens:
        async with async_session_factory() as session:
            session.add(
                TokenUsage(
                    user_id=ALICE,
                    step="generate_answer",
                    kind=TokenUsageKind.CHAT,
                    model="m",
                    input_tokens=tokens - 5,
                    output_tokens=5,
                    total_tokens=tokens,
                    run_id=entry.run_id,
                )
            )
            await session.commit()
    await routine_scheduler._conclude(entry.id, entry.run_id, status)
    return (await history(routine_id))[-1]


async def index_document(collection_id: str, name: str = "nouveau.pdf") -> None:
    async with async_session_factory() as session:
        session.add(
            Document(collection_id=uuid.UUID(collection_id), name=name, type="url", status=DocumentStatus.INDEXED)
        )
        await session.commit()


# --- a run for a date ---


async def test_a_due_routine_runs_in_the_name_of_the_person_without_tools_nor_administrator_rights(client):
    await enable()
    shared = await collection()
    become(ROOT, admin=True)  # even an administrator's routine runs as a person
    made = await make(client, [shared], web_search=True)
    await make_due(made["id"])
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=ROOT, display="Root", email="root@example.com", groups=["direction"]))
        await session.commit()

    started = await routine_scheduler.sweep()

    [run] = await runs_of(ROOT)
    assert started == 1 and run.query == "Qu'est-ce qui a changé ?"
    assert (run.user_is_admin, run.interactive, run.web_search_enabled) == (False, False, True)
    assert run.assistant_disabled_tools == ["call_tool"] and run.pinned_collection_ids == [shared]
    assert "direction" in run.user_groups
    assert client.started == [(str(run.id), None)]  # no token of the person
    [entry] = await history(made["id"])
    assert entry.status == RoutineRunStatus.RUNNING and entry.trigger == "schedule" and entry.run_id == run.id
    assert client.followed[0][:2] == (entry.id, run.id)


async def test_the_groups_of_muffin_are_read_at_each_run(client):
    await enable()
    shared = await collection()
    made = await make(client, [shared])
    become("owner")
    group = (await client.post("/api/groups", json={"name": "Équipe A"})).json()
    await client.post(f"/api/groups/{group['id']}/members", json={"user_id": ALICE})
    await make_due(made["id"])

    await routine_scheduler.sweep()

    [run] = await runs_of(ALICE)
    assert group["id"] in run.user_groups


async def test_each_run_makes_a_conversation_with_the_question_and_the_next_date_moves_past_now(client):
    await enable()
    made = await make(client)
    await make_due(made["id"], minutes=300)

    await routine_scheduler.sweep()
    second = await routine_scheduler.sweep()

    after = await load(made["id"])
    [entry] = await history(made["id"])
    async with async_session_factory() as session:
        conversation = await session.get(Conversation, entry.conversation_id)
        messages = list(
            (await session.execute(select(Message).where(Message.conversation_id == conversation.id))).scalars()
        )
    assert second == 0 and after.next_run_at > datetime.now(UTC) and after.last_run_at is not None
    assert conversation.title.startswith("Routine : Veille – ") and conversation.user_id == ALICE
    assert [m.content for m in messages] == ["Qu'est-ce qui a changé ?"]


async def test_two_sweeps_at_the_same_time_make_one_run_for_a_date(client):
    await enable()
    made = await make(client)
    await make_due(made["id"])

    results = await asyncio.gather(routine_scheduler.sweep(), routine_scheduler.sweep())

    assert sum(results) == 1 and len(await history(made["id"])) == 1 and len(await runs_of(ALICE)) == 1


async def test_a_routine_missed_during_an_outage_runs_once_not_once_per_missed_date(client):
    await enable()
    made = await make(client, schedule={"kind": "interval", "interval_minutes": 60})
    await make_due(made["id"], minutes=60 * 9)

    await routine_scheduler.sweep()
    await end(made["id"])
    await routine_scheduler.sweep()

    assert len(await history(made["id"])) == 1
    assert (await load(made["id"])).next_run_at > datetime.now(UTC)


async def test_nothing_runs_while_the_function_is_off(client):
    await enable()
    made = await make(client)
    await make_due(made["id"])
    async with async_session_factory() as session:
        await session.execute(update(RoutineSettings).values(enabled=False))
        await session.commit()

    assert await routine_scheduler.sweep() == 0 and await history(made["id"]) == []


async def test_a_paused_routine_does_not_run(client):
    await enable()
    made = await make(client)
    await client.post(f"/api/routines/{made['id']}/pause")

    assert await routine_scheduler.sweep() == 0 and await history(made["id"]) == []


# --- the reasons for not running ---


async def test_a_routine_that_is_still_running_is_skipped_and_says_so(client):
    await enable()
    made = await make(client)
    await make_due(made["id"])
    await routine_scheduler.sweep()
    await make_due(made["id"])

    started = await routine_scheduler.sweep()

    first, second = await history(made["id"])
    assert started == 0 and first.status == RoutineRunStatus.RUNNING
    assert (second.status, second.skip_reason) == (RoutineRunStatus.SKIPPED, "previous_running")
    assert len(await runs_of(ALICE)) == 1


async def test_with_only_if_new_nothing_is_asked_while_no_document_is_new(client):
    await enable()
    shared = await collection()
    made = await make(client, [shared], condition="only_if_new")
    await make_due(made["id"])

    first = await routine_scheduler.sweep()
    skipped = await history(made["id"])
    await index_document(shared)
    await make_due(made["id"])
    second = await routine_scheduler.sweep()

    assert first == 0 and [(r.status, r.skip_reason) for r in skipped] == [
        (RoutineRunStatus.SKIPPED, "no_new_documents")
    ]
    assert second == 1 and len(await runs_of(ALICE)) == 1  # the skipped date cost nothing: no run of the agent


async def test_a_document_still_being_processed_is_not_new_yet(client):
    await enable()
    shared = await collection()
    made = await make(client, [shared], condition="only_if_new")
    async with async_session_factory() as session:
        session.add(
            Document(collection_id=uuid.UUID(shared), name="en cours.pdf", type="url", status=DocumentStatus.INDEXING)
        )
        await session.commit()
    await make_due(made["id"])

    assert await routine_scheduler.sweep() == 0


async def test_with_only_if_new_the_sub_collections_count_when_asked(client):
    await enable()
    parent = await collection(name="Parent")
    child = await collection(name="Enfant")
    async with async_session_factory() as session:
        row = await session.get(Collection, uuid.UUID(child))
        row.parent_id = uuid.UUID(parent)
        await session.commit()
    made = await make(client, [parent], condition="only_if_new", include_descendants=True)
    await index_document(child)
    await make_due(made["id"])

    assert await routine_scheduler.sweep() == 1


async def test_by_hand_the_condition_does_not_apply_but_a_run_in_progress_does(client):
    await enable()
    shared = await collection()
    made = await make(client, [shared], condition="only_if_new")

    first = await client.post(f"/api/routines/{made['id']}/run")
    second = await client.post(f"/api/routines/{made['id']}/run")

    assert first.json()["run"]["status"] == "running" and first.json()["run"]["trigger"] == "manual"
    assert second.json()["run"]["status"] == "skipped" and second.json()["run"]["skip_reason"] == "previous_running"
    assert len(await runs_of(ALICE)) == 1


async def test_the_runs_of_a_person_in_a_day_are_bounded(client):
    await enable(max_runs_per_user_per_day=1)
    made = await make(client)
    await make_due(made["id"])
    await routine_scheduler.sweep()
    await end(made["id"])
    await make_due(made["id"])

    await routine_scheduler.sweep()
    by_hand = await client.post(f"/api/routines/{made['id']}/run")

    assert [r.skip_reason for r in (await history(made["id"]))[1:]] == ["daily_limit", "daily_limit"]
    assert by_hand.json()["run"]["skip_reason"] == "daily_limit" and len(await runs_of(ALICE)) == 1


async def test_the_runs_at_the_same_time_in_the_whole_application_are_bounded(client):
    await enable(max_concurrent=1)
    first, second = await make(client), await make(client)
    await make_due(first["id"], 2)
    await make_due(second["id"], 1)

    one = await routine_scheduler.sweep()
    nothing = await routine_scheduler.sweep()
    await end(first["id"])
    the_other = await routine_scheduler.sweep()

    assert (one, nothing, the_other) == (1, 0, 1) and len(await runs_of(ALICE)) == 2
    assert await history(second["id"]) != []


# --- the rights of the person, as they are then ---


async def test_a_collection_that_is_no_longer_readable_is_left_out_and_the_person_is_told(client):
    await enable()
    kept, lost = await collection(name="Règlements"), await collection(name="Budget")
    made = await make(client, [kept, lost])
    async with async_session_factory() as session:
        row = await session.get(Collection, uuid.UUID(lost))
        row.visibility = CollectionVisibility.PRIVATE
        await session.commit()
    await make_due(made["id"])

    await routine_scheduler.sweep()
    entry = await end(made["id"])

    [run] = await runs_of(ALICE)
    [notification] = await notifications_of(ALICE)
    assert run.pinned_collection_ids == [kept]
    assert entry.note == "Pas accessible à vous : Budget" and "Budget" in notification.summary


async def test_with_nothing_left_to_read_the_run_is_skipped_counted_as_a_failure_and_told(client):
    await enable()
    shared = await collection()
    made = await make(client, [shared])
    async with async_session_factory() as session:
        row = await session.get(Collection, uuid.UUID(shared))
        row.visibility = CollectionVisibility.PRIVATE
        await session.commit()
    await make_due(made["id"])

    started = await routine_scheduler.sweep()

    [entry] = await history(made["id"])
    [notification] = await notifications_of(ALICE)
    assert started == 0 and (entry.status, entry.skip_reason) == (RoutineRunStatus.SKIPPED, "access_lost")
    assert (await load(made["id"])).consecutive_failures == 1 and await runs_of(ALICE) == []
    assert notification.type == "routine.failed" and "plus accessibles" in notification.summary


# --- what follows a run ---


async def test_a_run_that_succeeds_is_recorded_with_its_tokens_and_the_person_is_told_without_the_answer(client):
    await enable()
    made = await make(client)
    await make_due(made["id"])
    await routine_scheduler.sweep()

    entry = await end(made["id"], tokens=1234)

    [notification] = await notifications_of(ALICE)
    assert (entry.status, entry.total_tokens) == (RoutineRunStatus.SUCCEEDED, 1234) and entry.finished_at
    assert notification.type == "routine.completed" and notification.summary == "Le résultat est prêt."
    assert notification.link == f"/c/{entry.conversation_id}"
    assert (await load(made["id"])).consecutive_failures == 0


@pytest.mark.parametrize(
    ("notify", "succeeded", "expected"),
    [
        ("always", True, ["routine.completed"]),
        ("always", False, ["routine.failed"]),
        ("failure", True, []),
        ("failure", False, ["routine.failed"]),
        ("never", True, []),
        ("never", False, []),
    ],
)
async def test_the_person_is_told_as_they_chose(client, notify, succeeded, expected):
    await enable()
    made = await make(client, notify=notify)
    await make_due(made["id"])
    await routine_scheduler.sweep()

    await end(made["id"], RunStatus.COMPLETED if succeeded else RunStatus.FAILED)

    assert [n.type for n in await notifications_of(ALICE)] == expected


async def test_failures_in_a_row_put_the_routine_aside_and_tell_why_and_a_success_resets_the_count(client):
    await enable(max_consecutive_failures=2)
    made = await make(client)

    for status in (RunStatus.FAILED, RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.FAILED):
        await make_due(made["id"])
        await routine_scheduler.sweep()
        entry = await end(made["id"], status)

    routine = await load(made["id"])
    assert entry.status == RoutineRunStatus.FAILED and "répondre" in entry.error
    assert (routine.state.value, routine.suspended_reason, routine.next_run_at) == ("suspended", "failures", None)
    assert [n.type for n in await notifications_of(ALICE)] == [
        "routine.failed",
        "routine.completed",
        "routine.failed",
        "routine.failed",
        "routine.suspended",
    ]
    assert await routine_scheduler.sweep() == 0
    resumed = await client.post(f"/api/routines/{made['id']}/resume")
    assert resumed.json()["state"] == "active" and resumed.json()["consecutive_failures"] == 0


async def test_a_run_that_takes_too_long_is_stopped_and_fails(client, monkeypatch):
    await enable()
    made = await make(client)
    await make_due(made["id"])
    await routine_scheduler.sweep()
    [entry] = await history(made["id"])
    cancelled: list[str] = []
    monkeypatch.setattr(agent_runner, "cancel", cancelled.append)

    await routine_scheduler._follow(entry.id, entry.run_id, 0)

    [after] = await history(made["id"])
    async with async_session_factory() as session:
        run = await session.get(Run, entry.run_id)
    assert cancelled == [str(entry.run_id)] and run.status == RunStatus.FAILED
    assert after.status == RoutineRunStatus.FAILED and "délai" in after.error.lower()


async def test_a_run_that_nobody_follows_any_more_is_closed_as_failed(client):
    await enable()
    made = await make(client)
    async with async_session_factory() as session:
        session.add(
            RoutineRun(
                routine_id=uuid.UUID(made["id"]),
                status=RoutineRunStatus.RUNNING,
                trigger="schedule",
                started_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
        await session.commit()

    await routine_scheduler.housekeeping(datetime.now(UTC), force=True)

    [entry] = await history(made["id"])
    assert entry.status == RoutineRunStatus.FAILED and (await load(made["id"])).consecutive_failures == 1


async def test_one_conversation_per_routine_when_asked(client):
    await enable()
    made = await make(client, result_mode="single_conversation")

    conversations = []
    for _ in range(2):
        await make_due(made["id"])
        await routine_scheduler.sweep()
        conversations.append((await end(made["id"])).conversation_id)

    async with async_session_factory() as session:
        asked = list(
            (await session.execute(select(Message).where(Message.conversation_id == conversations[0]))).scalars()
        )
    assert conversations[0] == conversations[1] and len(asked) == 2


# --- the owner who left ---


async def test_the_routines_of_someone_who_has_not_come_back_for_a_long_time_are_suspended_and_told(client):
    await enable(inactive_days=60)
    gone, here = await make(client), None
    become(BOB)
    here = await make(client)
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=ALICE, display="Alice", last_seen_at=datetime.now(UTC) - timedelta(days=90)))
        session.add(UserProfile(user_id=BOB, display="Bob", last_seen_at=datetime.now(UTC) - timedelta(days=2)))
        await session.commit()

    await routine_scheduler.housekeeping(datetime.now(UTC), force=True)

    away, present = await load(gone["id"]), await load(here["id"])
    assert (away.state.value, away.suspended_reason) == ("suspended", "inactive") and present.state.value == "active"
    assert [n.type for n in await notifications_of(ALICE)] == ["routine.suspended"]
    assert await notifications_of(BOB) == []


# --- what they cost ---


async def test_what_the_routines_cost_is_shown_apart_to_the_person_and_to_the_administrator(client):
    await enable()
    made = await make(client)
    await make_due(made["id"])
    await routine_scheduler.sweep()
    await end(made["id"], tokens=400)
    await make_due(made["id"])
    await routine_scheduler.sweep()
    await make_due(made["id"])
    await routine_scheduler.sweep()  # skipped: the run before is still going - it asked nothing

    mine = (await client.get("/api/usage/me")).json()
    become(BOB)
    bobs = (await client.get("/api/usage/me")).json()
    become(ROOT, admin=True)
    everyone = (await client.get("/api/admin/usage")).json()
    listed = (await client.get("/api/admin/routines")).json()["items"]

    assert mine["routines"] == {"runs": 2, "total_tokens": 400} and bobs["routines"] == {"runs": 0, "total_tokens": 0}
    assert everyone["routines"] == {"runs": 2, "total_tokens": 400} and listed[0]["tokens_30_days"] == 400


# --- the guardrails on the input ---


async def with_guardrail(**fields):
    from app.models.guardrail import Enforcement, Guardrail, GuardrailType

    async with async_session_factory() as session:
        session.add(
            Guardrail(
                name="Pas d'IBAN",
                type=GuardrailType.RULES,
                config={"builtins": ["iban"]},
                enabled=True,
                enforcement=Enforcement.BLOCK,
                refusal_message="Pas de coordonnées bancaires.",
                **fields,
            )
        )
        await session.commit()


async def without_guardrails():
    from app.models.guardrail import Guardrail

    async with async_session_factory() as session:
        await session.execute(delete(Guardrail))
        await session.commit()


async def test_a_question_the_guardrails_would_stop_is_refused_when_the_routine_is_written_and_changed(client):
    await enable()
    await with_guardrail()
    iban = "FR76 3000 6000 0112 3456 7890 189"
    try:
        refused = await client.post("/api/routines", json=body(question=f"Surveille le compte {iban}"))
        made = await make(client, question="Quoi de neuf ?")
        changed = await client.patch(f"/api/routines/{made['id']}", json={"question": f"Et le compte {iban} ?"})
    finally:
        await without_guardrails()

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "question_refusee"
    assert refused.json()["detail"]["message"] == "Pas de coordonnées bancaires."
    assert changed.status_code == 422 and (await load(made["id"])).question == "Quoi de neuf ?"


async def test_a_run_whose_question_the_guardrails_stopped_is_a_failure_and_the_person_is_told(client):
    await enable()
    made = await make(client)
    await make_due(made["id"])
    await routine_scheduler.sweep()
    [entry] = await history(made["id"])
    async with async_session_factory() as session:
        run = await session.get(Run, entry.run_id)
        run.guardrail_outcome = "blocked"  # what the guardrails wrote when they stopped the request
        await session.commit()

    done = await end(made["id"], RunStatus.COMPLETED)

    [notification] = await notifications_of(ALICE)
    assert done.status == RoutineRunStatus.FAILED and "politique d'usage" in done.error
    assert notification.type == "routine.failed" and (await load(made["id"])).consecutive_failures == 1
