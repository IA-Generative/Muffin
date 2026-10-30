"""A collection copied from another system (#464) is read, searched and talked to in Muffin, and changed there: every
way of changing it answers 409 - until Muffin has taken it over (#462), when it is a collection like any other."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document, DocumentType


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Collection))
        await session.commit()


async def _copy(*, adopted: bool = False) -> tuple[uuid.UUID, uuid.UUID]:
    """A copy of a collection of Open WebUI, owned by the caller, with one document."""
    async with async_session_factory() as session:
        collection = Collection(
            owner_id="dev-user",
            name="Copiée",
            source="owui",
            external_id=f"kb-{uuid.uuid4()}",
            adopted_at=datetime.now(UTC) if adopted else None,
        )
        collection.settings = CollectionSettings(embedding_model="bge")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="a.pdf", type=DocumentType.FILE)
        session.add(document)
        await session.commit()
        return collection.id, document.id


def _changes(collection_id, document_id):
    base = f"/api/collections/{collection_id}"
    return {
        "rename": ("PATCH", base, {"json": {"name": "Autre"}}),
        "settings": ("PATCH", f"{base}/settings", {"json": {"chunk_size": 500}}),
        "visibility": ("PATCH", f"{base}/visibility", {"json": {"visibility": "public"}}),
        "share": ("POST", f"{base}/shares", {"json": {"subject_type": "user", "identifier": "a@example.test"}}),
        "delete the collection": ("DELETE", base, {}),
        "upload a file": ("POST", f"{base}/documents/file", {"files": {"file": ("x.txt", b"hello", "text/plain")}}),
        "add a URL": ("POST", f"{base}/documents/url", {"json": {"url": "https://example.test/page"}}),
        "delete a document": ("DELETE", f"{base}/documents/{document_id}", {}),
        "reprocess a document": ("POST", f"{base}/documents/{document_id}/reprocess", {}),
        "reprocess the failed ones": ("POST", f"{base}/documents/reprocess-failed", {}),
        "schedule a refresh": (
            "PUT",
            f"{base}/documents/{document_id}/refresh-schedule",
            {"json": {"schedule": {"kind": "interval", "interval_minutes": 60}}},
        ),
    }


@pytest.mark.parametrize(
    "action",
    [
        "rename",
        "settings",
        "visibility",
        "share",
        "delete the collection",
        "upload a file",
        "add a URL",
        "delete a document",
        "reprocess a document",
        "reprocess the failed ones",
        "schedule a refresh",
    ],
)
async def test_every_way_of_changing_a_copy_is_refused(client, action):
    collection_id, document_id = await _copy()
    method, url, kwargs = _changes(collection_id, document_id)[action]

    response = await client.request(method, url, **kwargs)

    assert response.status_code == 409, response.text
    async with async_session_factory() as session:
        collection = await session.get(Collection, collection_id)
        document = await session.get(Document, document_id)
    assert (collection.name, collection.visibility.value) == ("Copiée", "private") and document is not None


async def test_a_copy_can_still_be_read_and_its_shares_listed(client):
    collection_id, document_id = await _copy()

    assert (await client.get(f"/api/collections/{collection_id}")).status_code == 200
    assert (await client.get(f"/api/collections/{collection_id}/shares")).status_code == 200
    assert (await client.get(f"/api/collections/{collection_id}/documents")).status_code == 200


async def test_a_copy_says_it_is_one_and_cannot_be_edited(client):
    collection_id, _ = await _copy()

    body = (await client.get(f"/api/collections/{collection_id}")).json()

    assert (body["copied"], body["adopted"], body["can_edit"]) == (True, False, False)


async def test_a_collection_made_in_muffin_is_neither_copied_nor_adopted(client):
    created = (await client.post("/api/collections", json={"name": "À moi"})).json()

    assert (created["copied"], created["adopted"], created["can_edit"]) == (False, False, True)
    assert (await client.patch(f"/api/collections/{created['id']}", json={"name": "Encore à moi"})).status_code == 200


async def test_an_adopted_collection_is_changed_like_any_other(client):
    collection_id, document_id = await _copy(adopted=True)

    body = (await client.get(f"/api/collections/{collection_id}")).json()
    renamed = await client.patch(f"/api/collections/{collection_id}", json={"name": "Autre"})
    visibility = await client.patch(f"/api/collections/{collection_id}/visibility", json={"visibility": "public"})

    assert (body["copied"], body["adopted"], body["can_edit"]) == (False, True, True)
    assert (renamed.status_code, visibility.status_code) == (200, 200)
