"""The notifications of the application (#524): theirs alone, counted, read, kept 90 days, chosen by type, and rung by
the events they stand for - without ever holding the text of an answer or leading away from the application."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.collection_import import CollectionImport, CollectionImportStatus
from app.models.document import Document
from app.models.group import Group
from app.models.notification import Notification, NotificationPreference
from app.models.report import Report
from app.models.token_usage import UserProfile
from app.schemas.collection_import import CollectionImportResult
from app.schemas.internal_document import DocumentStatusUpdate
from app.services import notification_service
from app.services.collection_import_service import CollectionImportService
from app.services.document_service import DocumentService
from app.services.notification_service import (
    DOCUMENT_FAILED,
    ROUTINE_COMPLETED,
    TYPES,
    NotificationService,
    notify,
)

ALICE, BOB = "alice", "bob"


def become(user_id: str, *, admin: bool = False) -> None:
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id=user_id, email=f"{user_id}@example.com", roles=[], is_admin=admin
    )


@pytest.fixture
async def client():
    become(ALICE)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        for model in (Notification, NotificationPreference, Collection, CollectionImport, Group, Report, UserProfile):
            await session.execute(delete(model))
        await session.commit()


async def ring(user_id=ALICE, type_=ROUTINE_COMPLETED, title="Titre", **fields) -> None:
    await notify(user_id, type_, title, fields.pop("summary", "Une ligne"), fields.pop("link", "/routines"), **fields)


async def listed(client, **params) -> dict:
    response = await client.get("/api/notifications", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- reading them ---


async def test_a_person_sees_only_their_own_notifications_newest_first(client):
    await ring(title="première")
    await ring(title="seconde")
    await ring(BOB, title="de Bob")

    mine = await listed(client)
    become(BOB)
    theirs = await listed(client)

    assert [item["title"] for item in mine["items"]] == ["seconde", "première"] and mine["unread"] == 2
    assert [item["title"] for item in theirs["items"]] == ["de Bob"]


async def test_the_unread_count_is_exact_and_marking_read_changes_it(client):
    for index in range(3):
        await ring(title=f"n{index}")
    first = (await listed(client))["items"][0]

    assert (await client.get("/api/notifications/unread-count")).json() == {"count": 3}
    one = await client.post("/api/notifications/read", json={"ids": [first["id"]]})
    assert one.json() == {"count": 2}
    assert [item["read"] for item in (await listed(client))["items"]] == [True, False, False]
    assert (await listed(client, unread_only="true"))["unread"] == 2
    assert len((await listed(client, unread_only="true"))["items"]) == 2
    everything = await client.post("/api/notifications/read", json={})
    assert everything.json() == {"count": 0}


async def test_someone_else_cannot_mark_read_nor_delete_what_is_not_theirs(client):
    await ring(title="à Alice")
    mine = (await listed(client))["items"][0]
    become(BOB)

    marked = await client.post("/api/notifications/read", json={"ids": [mine["id"]]})
    deleted = await client.delete(f"/api/notifications/{mine['id']}")

    assert marked.json() == {"count": 0} and deleted.status_code == 404
    become(ALICE)
    assert (await listed(client))["unread"] == 1


async def test_a_notification_is_deleted_by_its_owner(client):
    await ring()
    item = (await listed(client))["items"][0]

    assert (await client.delete(f"/api/notifications/{item['id']}")).status_code == 204
    assert (await listed(client))["items"] == []
    assert (await client.delete(f"/api/notifications/{item['id']}")).status_code == 404


async def test_the_list_goes_on_by_cursor_without_repeating_or_missing_one(client):
    for index in range(5):
        await ring(title=f"n{index}")

    first = await listed(client, limit=2)
    second = await listed(client, limit=2, cursor=first["next_cursor"])
    third = await listed(client, limit=2, cursor=second["next_cursor"])

    titles = [item["title"] for page in (first, second, third) for item in page["items"]]
    assert titles == ["n4", "n3", "n2", "n1", "n0"] and third["next_cursor"] is None
    assert (await client.get("/api/notifications", params={"cursor": "not-a-cursor"})).status_code == 422


async def test_what_is_older_than_ninety_days_is_forgotten(client):
    await ring(title="vieille")
    await ring(title="récente")
    async with async_session_factory() as session:
        await session.execute(
            update(Notification)
            .where(Notification.title == "vieille")
            .values(created_at=datetime.now(UTC) - timedelta(days=91))
        )
        await session.commit()
    async with async_session_factory() as session:
        removed = await NotificationService(session).purge()

    assert removed == 1 and [item["title"] for item in (await listed(client))["items"]] == ["récente"]


async def test_a_person_keeps_a_bounded_number_of_notifications(client, monkeypatch):
    monkeypatch.setattr(notification_service, "KEEP_PER_USER", 3)
    for index in range(6):
        await ring(title=f"n{index}")

    assert [item["title"] for item in (await listed(client))["items"]] == ["n5", "n4", "n3"]


# --- what a notification may hold ---


async def test_a_link_leads_into_the_application_only(client):
    await ring(title="a", link="/c/123")
    await ring(title="b", link="https://evil.example/phish")
    await ring(title="c", link="//evil.example/phish")

    links = {item["title"]: item["link"] for item in (await listed(client))["items"]}

    assert links == {"a": "/c/123", "b": None, "c": None}


async def test_a_type_that_does_not_exist_is_refused_and_a_failure_of_the_bell_never_breaks_the_caller(client):
    with pytest.raises(notification_service.UnknownNotificationTypeError):
        async with async_session_factory() as session:
            await NotificationService(session).notify(ALICE, "made.up", "x")

    await notify(ALICE, "made.up", "x")  # logged, not raised
    await notify(None, ROUTINE_COMPLETED, "x")  # nobody to tell

    assert (await listed(client))["items"] == []


# --- preferences ---


async def test_by_default_everything_is_on_and_a_type_turned_off_is_no_longer_rung(client):
    default = (await client.get("/api/notifications/preferences")).json()
    assert [item["type"] for item in default] == list(TYPES) and all(item["app"] for item in default)

    changed = await client.put(
        "/api/notifications/preferences", json={"preferences": [{"type": ROUTINE_COMPLETED, "app": False}]}
    )
    await ring(title="muette")
    await ring(type_=DOCUMENT_FAILED, title="entendue")

    assert changed.status_code == 200
    assert {item["type"]: item["app"] for item in changed.json()}[ROUTINE_COMPLETED] is False
    assert [item["title"] for item in (await listed(client))["items"]] == ["entendue"]


async def test_preferences_are_each_persons_and_an_unknown_type_is_refused(client):
    await client.put(
        "/api/notifications/preferences", json={"preferences": [{"type": ROUTINE_COMPLETED, "app": False}]}
    )
    become(BOB)

    bobs = {item["type"]: item["app"] for item in (await client.get("/api/notifications/preferences")).json()}
    refused = await client.put("/api/notifications/preferences", json={"preferences": [{"type": "x.y", "app": False}]})

    assert bobs[ROUTINE_COMPLETED] is True and refused.status_code == 422


# --- the person is seen ---


async def test_looking_at_the_unread_count_tells_that_the_person_is_there_but_not_every_minute(client):
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=ALICE, display="Alice", last_seen_at=datetime.now(UTC) - timedelta(days=2)))
        await session.commit()

    await client.get("/api/notifications/unread-count")
    async with async_session_factory() as session:
        first = (await session.get(UserProfile, ALICE)).last_seen_at
    await client.get("/api/notifications/unread-count")
    async with async_session_factory() as session:
        second = (await session.get(UserProfile, ALICE)).last_seen_at

    assert datetime.now(UTC) - first < timedelta(minutes=1) and second == first


# --- the events that ring ---


async def _collection(owner="owner") -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner, name="Règlements")
        session.add(collection)
        await session.commit()
        return collection.id


async def test_a_document_that_fails_tells_who_added_it_once_and_never_says_why(client):
    collection_id = await _collection()
    async with async_session_factory() as session:
        document = Document(collection_id=collection_id, name="rapport.pdf", type="url", added_by_user_id=ALICE)
        session.add(document)
        await session.commit()
        document_id = document.id

    for _ in range(2):  # a retry that fails again does not ring twice
        async with async_session_factory() as session:
            await DocumentService(session).update_status(
                document_id, DocumentStatusUpdate(status="error", summary="Traceback: secret path /srv/x")
            )

    [item] = (await listed(client))["items"]
    assert item["type"] == DOCUMENT_FAILED and "rapport.pdf" in item["summary"]
    assert "Traceback" not in item["summary"] + item["title"] and item["link"].endswith(f"/documents/{document_id}")
    become(BOB)
    assert (await listed(client))["items"] == []


async def test_a_finished_import_tells_its_owner_with_counts_and_no_file_name(client):
    collection_id = await _collection(ALICE)
    async with async_session_factory() as session:
        row = CollectionImport(
            owner_id=ALICE,
            owner_display="Alice",
            archive_name="dossier.zip",
            status=CollectionImportStatus.RUNNING,
            root_collection_id=collection_id,
        )
        session.add(row)
        await session.commit()
        import_id = row.id

    async with async_session_factory() as session:
        await CollectionImportService(session).finish(
            import_id,
            CollectionImportResult(
                status="completed", summary={"documents_created": 7, "skipped": [{"path": "secret/a.doc"}]}
            ),
        )

    [item] = (await listed(client))["items"]
    assert item["title"] == "Import terminé" and "7 document(s)" in item["summary"]
    assert "secret" not in item["summary"] and item["link"] == f"/collections/{collection_id}"


async def test_a_collection_shared_with_a_group_tells_its_members_but_not_the_one_who_shared(client):
    become("owner")
    group = (await client.post("/api/groups", json={"name": "Équipe A"})).json()
    await client.post(f"/api/groups/{group['id']}/members", json={"user_id": ALICE})
    collection = (await client.post("/api/collections")).json()
    await client.patch(f"/api/collections/{collection['id']}", json={"name": "Règlements"})

    shared = await client.post(
        f"/api/collections/{collection['id']}/shares",
        json={"subject_type": "group", "group_id": group["id"], "permission": "read"},
    )
    owners = await listed(client)
    become(ALICE)
    members = await listed(client)

    assert shared.status_code == 201 and owners["items"] == []
    [item] = members["items"]
    assert item["type"] == "share.received" and item["link"] == f"/collections/{collection['id']}"


async def test_the_status_of_a_report_tells_the_one_who_made_it_when_it_changes(client):
    created = await client.post(
        "/api/reports", data={"type": "bug", "title": "Bouton cassé", "description": "Ça casse"}
    )
    report_id = created.json()["id"]
    become("admin", admin=True)

    await client.patch(f"/api/admin/reports/{report_id}", json={"status": "resolved", "admin_response": "Corrigé"})
    await client.patch(f"/api/admin/reports/{report_id}", json={"status": "resolved", "admin_response": "Encore"})
    become(ALICE)

    [item] = (await listed(client))["items"]
    assert item["type"] == "feedback.status" and "Bouton cassé" in item["summary"] and "traité" in item["summary"]
    assert "Corrigé" not in item["summary"]
    become("admin", admin=True)
    assert (await listed(client))["items"] == []
