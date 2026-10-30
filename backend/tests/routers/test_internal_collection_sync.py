"""The collections copied from Open WebUI (#453): what the worker writes, and who it is shared with."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import (
    Collection,
    CollectionSettings,
    CollectionShare,
    CollectionVisibility,
    ShareSubjectType,
)
from app.models.document import Document
from app.models.group import Group
from app.models.index_rebuild import IndexRebuild, IndexRebuildStatus

API_KEY = "test-worker-key"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.execute(delete(Group))
        await session.commit()


async def _put(client, external_id="kb1", **overrides):
    body = {"name": "Procédures", "owner_id": "sub-owner", "embedding_model": "bge-multilingual-gemma2", **overrides}
    return await client.put(f"/api/internal/synced-collections/owui/{external_id}", headers=HEADERS, json=body)


async def _group(client, external_id="g1", name="Équipe A") -> str:
    response = await client.put(
        f"/api/internal/groups/owui/{external_id}", headers=HEADERS, json={"name": name, "member_ids": []}
    )
    return response.json()["id"]


async def _shares(collection_id) -> set[tuple[ShareSubjectType, str]]:
    async with async_session_factory() as session:
        rows = await session.scalars(select(CollectionShare).where(CollectionShare.collection_id == collection_id))
        return {(share.subject_type, share.subject_id) for share in rows}


async def test_the_worker_key_is_required(client):
    response = await client.put("/api/internal/synced-collections/owui/kb1", json={})
    assert response.status_code == 401


async def test_a_collection_is_created_as_a_copy_with_its_owner_and_model(client):
    body = (await _put(client, description="Les procédures")).json()

    assert (body["created"], body["shares_added"], body["unknown_groups"]) == (True, 0, [])
    async with async_session_factory() as session:
        collection = (
            await session.scalars(
                select(Collection).where(Collection.id == body["id"]).options(selectinload(Collection.settings))
            )
        ).one()
    assert (collection.source, collection.external_id) == ("owui", "kb1")
    assert (collection.owner_id, collection.name, collection.description) == (
        "sub-owner",
        "Procédures",
        "Les procédures",
    )
    assert collection.visibility == CollectionVisibility.PRIVATE
    assert collection.settings.embedding_model == "bge-multilingual-gemma2"


async def test_syncing_again_changes_nothing(client):
    first = (await _put(client, user_shares=[{"subject_id": "sub-1", "email": "a@example.test"}])).json()
    second = (await _put(client, user_shares=[{"subject_id": "sub-1", "email": "a@example.test"}])).json()

    assert second["id"] == first["id"]
    assert (second["created"], second["shares_added"], second["shares_removed"]) == (False, 0, 0)


async def test_public_and_name_follow_the_other_system(client):
    first = (await _put(client)).json()
    await _put(client, name="Renommée", owner_id="sub-new", public=True)

    async with async_session_factory() as session:
        collection = await session.get(Collection, first["id"])
    assert (collection.name, collection.owner_id, collection.visibility) == (
        "Renommée",
        "sub-new",
        CollectionVisibility.PUBLIC,
    )


async def test_it_is_shared_with_the_users_and_the_groups_it_is_read_by(client):
    group_id = await _group(client)

    body = (
        await _put(
            client,
            user_shares=[{"subject_id": "sub-1", "email": "julie@example.com"}],
            group_external_ids=["g1"],
        )
    ).json()

    assert body["shares_added"] == 2
    assert await _shares(body["id"]) == {(ShareSubjectType.USER, "sub-1"), (ShareSubjectType.GROUP, group_id)}


async def test_a_share_that_is_gone_in_the_other_system_is_removed(client):
    group_id = await _group(client)
    first = (await _put(client, user_shares=[{"subject_id": "sub-1"}, {"subject_id": "sub-2"}])).json()
    second = (await _put(client, user_shares=[{"subject_id": "sub-2"}], group_external_ids=["g1"])).json()

    assert (second["shares_added"], second["shares_removed"]) == (1, 1)
    assert await _shares(first["id"]) == {(ShareSubjectType.USER, "sub-2"), (ShareSubjectType.GROUP, group_id)}


async def test_a_group_without_a_copy_is_reported_and_not_shared(client):
    body = (await _put(client, group_external_ids=["not-synced"])).json()

    assert body["unknown_groups"] == ["not-synced"]
    assert await _shares(body["id"]) == set()


async def test_the_collections_made_in_muffin_are_not_the_synchronisations_to_write(client):
    response = await client.put(
        "/api/internal/synced-collections/muffin/kb1",
        headers=HEADERS,
        json={"name": "x", "owner_id": "o", "embedding_model": "m"},
    )
    assert response.status_code == 400


async def test_listing_the_copies(client):
    await _put(client, "kb1")
    await _put(client, "kb2")

    response = await client.get("/api/internal/synced-collections/owui", headers=HEADERS)
    assert sorted(response.json()) == ["kb1", "kb2"]


async def test_a_collection_gone_from_the_other_system_is_dropped_with_its_files(client):
    await _put(client)
    document = await client.put(
        "/api/internal/synced-documents/owui/kb1/f1",
        headers=HEADERS,
        json={
            "collection_external_id": "kb1",
            "name": "a.pdf",
            "storage_key": "s3://bucket/open-webui/a.pdf",
            "chunks": [{"id": str(uuid.uuid4()), "index": 0, "text": "t", "token_count": 1}],
        },
    )
    document_id = document.json()["id"]

    assert (await client.delete("/api/internal/synced-collections/owui/kb1", headers=HEADERS)).status_code == 204

    assert (await client.get("/api/internal/synced-collections/owui", headers=HEADERS)).json() == []
    async with async_session_factory() as session:
        assert await session.get(Document, document_id) is None
        assert (await session.scalars(select(Chunk).where(Chunk.document_id == document_id))).all() == []


async def test_dropping_a_collection_that_is_not_there_is_not_found(client):
    assert (await client.delete("/api/internal/synced-collections/owui/nope", headers=HEADERS)).status_code == 404


async def test_a_share_that_writes_is_copied_as_such_and_follows_the_other_system(client):
    group_id = await _group(client)
    first = (
        await _put(
            client,
            user_shares=[{"subject_id": "sub-1", "permission": "write"}, {"subject_id": "sub-2"}],
            group_external_ids=["g1"],
            write_group_external_ids=["g1"],
        )
    ).json()

    assert await _permissions(first["id"]) == {
        (ShareSubjectType.USER, "sub-1"): "write",
        (ShareSubjectType.USER, "sub-2"): "read",
        (ShareSubjectType.GROUP, group_id): "write",
    }

    second = (
        await _put(
            client,
            user_shares=[{"subject_id": "sub-1"}, {"subject_id": "sub-2", "permission": "write"}],
            group_external_ids=["g1"],
        )
    ).json()

    assert (second["shares_added"], second["shares_removed"], second["shares_updated"]) == (0, 0, 3)
    assert await _permissions(first["id"]) == {
        (ShareSubjectType.USER, "sub-1"): "read",
        (ShareSubjectType.USER, "sub-2"): "write",
        (ShareSubjectType.GROUP, group_id): "read",
    }


async def _permissions(collection_id) -> dict:
    async with async_session_factory() as session:
        rows = await session.scalars(select(CollectionShare).where(CollectionShare.collection_id == collection_id))
        return {(share.subject_type, share.subject_id): share.permission for share in rows}


async def test_the_description_is_the_other_systems_only_at_the_start(client):
    """Muffin keeps it up to date from the summaries (#457): a later synchronisation must not write it back."""
    first = (await _put(client, name="Procédures", description="Celle d'Open WebUI")).json()
    async with async_session_factory() as session:
        collection = await session.get(Collection, first["id"])
        collection.description = "Celle que Muffin a écrite"
        await session.commit()

    await _put(client, name="Renommée", description="Celle d'Open WebUI, modifiée")

    async with async_session_factory() as session:
        collection = await session.get(Collection, first["id"])
    assert (collection.name, collection.description) == ("Renommée", "Celle que Muffin a écrite")


async def test_a_copy_never_asks_for_a_reindex(client):
    first = (await _put(client)).json()
    async with async_session_factory() as session:
        settings = (
            await session.scalars(select(CollectionSettings).where(CollectionSettings.collection_id == first["id"]))
        ).one()
        settings.reindex_required = True
        await session.commit()

    await _put(client)

    async with async_session_factory() as session:
        settings = (
            await session.scalars(select(CollectionSettings).where(CollectionSettings.collection_id == first["id"]))
        ).one()
    assert settings.reindex_required is False


# -- a collection Muffin took over, or is taking over (#462) ----------------------------------------------


async def _adopt(collection_id) -> None:
    async with async_session_factory() as session:
        (await session.get(Collection, uuid.UUID(collection_id))).adopted_at = datetime.now(UTC)
        await session.commit()


async def _rebuild(collection_id) -> None:
    async with async_session_factory() as session:
        session.add(
            IndexRebuild(
                collection_id=uuid.UUID(collection_id),
                status=IndexRebuildStatus.BUILDING,
                target_model="m",
                previous_model="m",
                requested_by="admin",
                adopts=True,
            )
        )
        await session.commit()


@pytest.fixture(params=["adopted", "being taken over"])
async def held(client, request):
    """A copy that is Muffin's now, or whose index Muffin is rebuilding to make it so."""
    collection_id = (await _put(client, user_shares=[{"subject_id": "sub-1", "email": "a@example.test"}])).json()["id"]
    await (_adopt if request.param == "adopted" else _rebuild)(collection_id)
    return collection_id


async def test_the_synchronisation_leaves_a_collection_muffin_took_over_as_it_is(client, held):
    response = await _put(client, name="Renommée", owner_id="someone-else", user_shares=[])

    assert response.status_code == 200 and response.json()["skipped"] is True
    async with async_session_factory() as session:
        collection = await session.get(Collection, uuid.UUID(held))
    assert (collection.name, collection.owner_id) == ("Procédures", "sub-owner")
    assert await _shares(held) == {(ShareSubjectType.USER, "sub-1")}


async def test_the_synchronisation_does_not_list_a_collection_muffin_took_over_for_deletion(client, held):
    assert (await client.get("/api/internal/synced-collections/owui", headers=HEADERS)).json() == []


async def test_a_collection_muffin_took_over_is_not_deleted_whatever_the_other_system_says(client, held):
    response = await client.delete("/api/internal/synced-collections/owui/kb1", headers=HEADERS)

    assert response.status_code == 409
    async with async_session_factory() as session:
        assert await session.get(Collection, uuid.UUID(held)) is not None


async def test_a_copy_still_synchronised_is_listed(client):
    await _put(client)

    assert (await client.get("/api/internal/synced-collections/owui", headers=HEADERS)).json() == ["kb1"]
