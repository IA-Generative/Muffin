"""The routines of the agent (#524), as a person uses them: off until an administrator turns them on, bounded by the
limits, theirs alone, with a rhythm that is checked and shown before it is kept."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionVisibility
from app.models.conversation import Conversation
from app.models.notification import Notification
from app.models.routine import Routine, RoutineSettings
from app.models.run import Run
from app.models.token_usage import TokenUsage, UserProfile
from app.services import run_service
from app.services.routine_runner import routine_scheduler

ALICE, BOB, ROOT = "alice", "bob", "root"
DAILY = {"kind": "daily", "time_of_day": "09:00:00", "timezone": "Europe/Paris"}


def become(user_id: str, *, admin: bool = False, groups: list[str] | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=admin, groups=groups or []
    )


@pytest.fixture
async def client(monkeypatch):
    """A client, an agent that is not started, nothing following a run, and a clean slate for what a test leaves."""
    started: list[tuple] = []
    followed: list[tuple] = []
    monkeypatch.setattr(run_service.agent_runner, "start", lambda *args, **kwargs: started.append(args))
    monkeypatch.setattr(routine_scheduler, "watch", lambda *args: followed.append(args))
    routine_scheduler._last_housekeeping = datetime.now(UTC)
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.started, http.followed = started, followed
        yield http
    routine_scheduler._last_housekeeping = None
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        for model in (Routine, Run, Conversation, Collection, Notification, RoutineSettings, UserProfile):
            await session.execute(delete(model))
        await session.execute(delete(TokenUsage).where(TokenUsage.user_id.in_([ALICE, BOB])))
        await session.commit()


async def enable(**limits) -> None:
    async with async_session_factory() as session:
        settings = await session.get(RoutineSettings, 1) or RoutineSettings(id=1)
        settings.enabled = True
        for field, value in limits.items():
            setattr(settings, field, value)
        session.add(settings)
        await session.commit()


async def collection(owner: str = "owner", name: str = "Règlements", public: bool = True) -> str:
    async with async_session_factory() as session:
        row = Collection(
            owner_id=owner,
            name=name,
            visibility=CollectionVisibility.PUBLIC if public else CollectionVisibility.PRIVATE,
        )
        session.add(row)
        await session.commit()
        return str(row.id)


def body(collection_ids: list[str] | None = None, **fields) -> dict:
    return {
        "name": "Veille",
        "question": "Qu'est-ce qui a changé ?",
        "collection_ids": collection_ids or [],
        "schedule": DAILY,
        **fields,
    }


async def make(client, collection_ids: list[str] | None = None, **fields) -> dict:
    response = await client.post("/api/routines", json=body(collection_ids, **fields))
    assert response.status_code == 201, response.text
    return response.json()


async def load(routine_id: str) -> Routine:
    async with async_session_factory() as session:
        return await session.get(Routine, uuid.UUID(routine_id))


# --- off by default ---


async def test_routines_are_off_until_an_administrator_turns_them_on(client):
    status_before = (await client.get("/api/routines/status")).json()
    refused = await client.post("/api/routines", json=body())
    await enable()
    status_after = (await client.get("/api/routines/status")).json()

    assert status_before["enabled"] is False and status_after["enabled"] is True
    assert refused.status_code == 404 and refused.json()["detail"]["code"] == "fonction_desactivee"
    assert (await client.get("/api/routines")).json() == []


async def test_the_status_tells_the_limits_and_what_the_person_has_used(client):
    await enable(max_active_per_user=4, min_interval_minutes=90, max_runs_per_user_per_day=7)
    await make(client)

    assert (await client.get("/api/routines/status")).json() == {
        "enabled": True,
        "max_active": 4,
        "min_interval_minutes": 90,
        "max_runs_per_day": 7,
        "active": 1,
        "runs_today": 0,
    }


# --- making one ---


async def test_a_routine_is_made_with_its_first_date_and_listed_with_no_run_yet(client):
    await enable()
    shared = await collection()

    made = await make(client, [shared], web_search=True)

    assert made["state"] == "active" and made["collection_ids"] == [shared] and made["web_search"] is True
    assert made["schedule"]["kind"] == "daily" and made["last_run"] is None
    assert datetime.fromisoformat(made["next_run_at"]) > datetime.now(UTC)
    assert [item["id"] for item in (await client.get("/api/routines")).json()] == [made["id"]]


@pytest.mark.parametrize(
    ("schedule", "code"),
    [
        ({"kind": "interval", "interval_minutes": 30}, "intervalle_trop_court"),
        ({"kind": "interval"}, "rythme_invalide"),
        ({"kind": "daily"}, "rythme_invalide"),
        ({"kind": "weekly", "time_of_day": "09:00:00", "weekdays": []}, "rythme_invalide"),
        ({"kind": "daily", "time_of_day": "09:00:00", "timezone": "Mars/Olympus"}, "rythme_invalide"),
    ],
)
async def test_a_rhythm_that_is_too_short_or_incomplete_is_refused_with_a_code(client, schedule, code):
    await enable(min_interval_minutes=60)

    refused = await client.post("/api/routines", json=body(schedule=schedule))

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == code


async def test_a_collection_the_person_cannot_read_is_refused(client):
    await enable()
    private = await collection(public=False)

    refused = await client.post("/api/routines", json=body([private]))

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "collection_inaccessible"


async def test_only_if_new_needs_collections_or_an_assistant_to_look_at(client):
    await enable()

    refused = await client.post("/api/routines", json=body(condition="only_if_new"))

    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "portee_requise"


async def test_a_person_has_a_bounded_number_of_active_routines_and_a_paused_one_does_not_count(client):
    await enable(max_active_per_user=2)
    first = await make(client)
    await make(client)

    third = await client.post("/api/routines", json=body())
    await client.post(f"/api/routines/{first['id']}/pause")
    fourth = await client.post("/api/routines", json=body())
    resumed = await client.post(f"/api/routines/{first['id']}/resume")

    assert third.status_code == 409 and third.json()["detail"]["code"] == "trop_de_routines"
    assert fourth.status_code == 201
    assert resumed.status_code == 409 and resumed.json()["detail"]["code"] == "trop_de_routines"


async def test_the_next_dates_of_a_rhythm_are_shown_before_it_is_kept(client):
    await enable()

    preview = await client.post("/api/routines/preview", json=DAILY)
    refused = await client.post("/api/routines/preview", json={"kind": "interval", "interval_minutes": 5})

    dates = [datetime.fromisoformat(date) for date in preview.json()["dates"]]
    assert len(dates) == 5 and all(
        b - a == timedelta(days=1) or b - a in (timedelta(hours=23), timedelta(hours=25))
        for a, b in zip(dates, dates[1:], strict=False)
    )
    assert refused.status_code == 422


# --- changing, pausing, deleting ---


async def test_changing_the_rhythm_moves_the_next_date_and_a_pause_clears_it(client):
    await enable()
    made = await make(client)

    changed = await client.patch(
        f"/api/routines/{made['id']}", json={"schedule": {"kind": "interval", "interval_minutes": 120}}
    )
    paused = await client.post(f"/api/routines/{made['id']}/pause")
    resumed = await client.post(f"/api/routines/{made['id']}/resume")

    soon = datetime.fromisoformat(changed.json()["next_run_at"]) - datetime.now(UTC)
    assert changed.json()["schedule"]["kind"] == "interval" and timedelta(hours=1) < soon <= timedelta(
        hours=2, minutes=1
    )
    assert paused.json()["state"] == "paused" and paused.json()["next_run_at"] is None
    assert resumed.json()["state"] == "active" and resumed.json()["next_run_at"] is not None


async def test_the_assistant_and_the_collections_can_be_changed_and_cleared(client):
    await enable()
    shared = await collection()
    made = await make(client, [shared])

    emptied = await client.patch(f"/api/routines/{made['id']}", json={"collection_ids": []})
    renamed = await client.patch(f"/api/routines/{made['id']}", json={"name": "Autre nom", "notify": "failure"})

    assert emptied.json()["collection_ids"] == [] and renamed.json()["name"] == "Autre nom"
    assert renamed.json()["notify"] == "failure"
    both = await client.patch(
        f"/api/routines/{made['id']}", json={"assistant_id": str(uuid.uuid4()), "clear_assistant": True}
    )
    assert both.status_code == 422


async def test_a_routine_is_deleted_with_its_history(client):
    await enable()
    made = await make(client)

    assert (await client.delete(f"/api/routines/{made['id']}")).status_code == 204
    assert (await client.get(f"/api/routines/{made['id']}")).status_code == 404
    assert (await client.get(f"/api/routines/{made['id']}/runs")).status_code == 404


# --- theirs alone ---


async def test_a_person_sees_changes_and_runs_only_their_own_routines(client):
    await enable()
    made = await make(client)
    become(BOB)

    assert (await client.get("/api/routines")).json() == []
    for call in (
        client.get(f"/api/routines/{made['id']}"),
        client.patch(f"/api/routines/{made['id']}", json={"name": "x"}),
        client.delete(f"/api/routines/{made['id']}"),
        client.post(f"/api/routines/{made['id']}/pause"),
        client.post(f"/api/routines/{made['id']}/resume"),
        client.post(f"/api/routines/{made['id']}/run"),
        client.get(f"/api/routines/{made['id']}/runs"),
    ):
        assert (await call).status_code == 404
    assert (await load(made["id"])).state.value == "active"


# --- the administrator ---


async def test_the_limits_are_set_by_an_administrator_only(client):
    refused = await client.patch("/api/admin/routines/settings", json={"enabled": True})
    become(ROOT, admin=True)
    changed = await client.patch(
        "/api/admin/routines/settings", json={"enabled": True, "max_active_per_user": 2, "inactive_days": 30}
    )
    invalid = await client.patch("/api/admin/routines/settings", json={"min_interval_minutes": 1})

    assert refused.status_code == 403
    assert changed.json()["enabled"] is True and changed.json()["max_active_per_user"] == 2
    assert changed.json()["inactive_days"] == 30 and changed.json()["min_interval_minutes"] == 60
    assert invalid.status_code == 422


async def test_an_administrator_lists_every_routine_without_its_question_and_suspends_one(client):
    await enable()
    made = await make(client, question="Une question confidentielle")
    become(ROOT, admin=True)

    listed = await client.get("/api/admin/routines")
    suspended = await client.post(f"/api/admin/routines/{made['id']}/suspend")
    become(ALICE)
    own = (await client.get(f"/api/routines/{made['id']}")).json()
    resumed = await client.post(f"/api/routines/{made['id']}/resume")
    edited = await client.patch(f"/api/routines/{made['id']}", json={"name": "x"})
    run_now = await client.post(f"/api/routines/{made['id']}/run")
    told = (await client.get("/api/notifications")).json()["items"]
    become(ROOT, admin=True)
    released = await client.post(f"/api/admin/routines/{made['id']}/release")
    become(ALICE)
    after = await client.post(f"/api/routines/{made['id']}/resume")

    [item] = listed.json()["items"]
    assert "question" not in item and "confidentielle" not in listed.text and item["name"] == "Veille"
    assert suspended.status_code == 204 and own["state"] == "suspended" and own["suspended_reason"] == "admin"
    assert own["next_run_at"] is None
    assert {r.status_code for r in (resumed, edited, run_now)} == {409}
    assert resumed.json()["detail"]["code"] == "suspendue_par_un_administrateur"
    assert [n["type"] for n in told] == ["routine.suspended"]
    assert released.status_code == 204 and after.json()["state"] == "active"


async def test_a_person_who_is_not_an_administrator_cannot_use_the_admin_routes(client):
    await enable()
    made = await make(client)

    responses = [
        await client.get("/api/admin/routines"),
        await client.get("/api/admin/routines/settings"),
        await client.post(f"/api/admin/routines/{made['id']}/suspend"),
    ]

    assert [r.status_code for r in responses] == [403, 403, 403]
