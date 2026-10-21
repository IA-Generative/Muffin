"""The hash of a file, and what a duplicate is (#300)."""

import hashlib
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.document import Document
from app.models.task import Task

PDF = b"%PDF-1.4 a report"
PDF_HASH = hashlib.sha256(PDF).hexdigest()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


@pytest.fixture(autouse=True)
def pipeline():
    """RustFS and the processing queue replaced."""
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            side_effect=lambda _id, bulk=False: str(uuid.uuid4()),
        ),
    ):
        yield


async def _collection(client) -> str:
    return (await client.post("/api/collections")).json()["id"]


async def _upload(client, collection_id, name="report.pdf", content=PDF, **params):
    return await client.post(
        f"/api/collections/{collection_id}/documents/file",
        params=params,
        files={"file": (name, content, "application/pdf")},
    )


async def _hash_of(document_id) -> str | None:
    async with async_session_factory() as session:
        return (await session.get(Document, uuid.UUID(document_id))).content_hash


async def test_an_uploaded_file_has_the_hash_of_its_bytes(client):
    collection_id = await _collection(client)

    response = await _upload(client, collection_id)

    assert response.status_code == 201
    assert await _hash_of(response.json()["id"]) == PDF_HASH


async def test_the_same_file_twice_in_a_collection_is_a_duplicate_to_confirm(client):
    collection_id = await _collection(client)
    first = (await _upload(client, collection_id)).json()

    # Another name, the same bytes: it is the same file.
    second = await _upload(client, collection_id, name="copy of report.pdf")

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_document"
    assert detail["document"] == {"id": first["id"], "name": "report.pdf"}
    # Refused before anything was stored: still one document.
    listed = (await client.get(f"/api/collections/{collection_id}/documents")).json()
    assert [document["id"] for document in listed] == [first["id"]]


async def test_a_duplicate_confirmed_is_added(client):
    collection_id = await _collection(client)
    await _upload(client, collection_id)

    response = await _upload(client, collection_id, allow_duplicate="true")

    assert response.status_code == 201
    assert len((await client.get(f"/api/collections/{collection_id}/documents")).json()) == 2


async def test_a_different_file_is_not_a_duplicate(client):
    collection_id = await _collection(client)
    await _upload(client, collection_id)

    assert (await _upload(client, collection_id, name="other.pdf", content=PDF + b"!")).status_code == 201


async def test_the_same_file_in_another_collection_is_never_blocked(client):
    first, second = await _collection(client), await _collection(client)
    await _upload(client, first)

    assert (await _upload(client, second)).status_code == 201


async def test_the_same_url_twice_in_a_collection_is_a_duplicate_to_confirm(client):
    collection_id = await _collection(client)
    url = f"/api/collections/{collection_id}/documents/url"
    first = (await client.post(url, json={"url": "https://example.com/page"})).json()

    second = await client.post(url, json={"url": "https://example.com/page"})
    other = await client.post(url, json={"url": "https://example.com/other"})
    confirmed = await client.post(url, json={"url": "https://example.com/page", "allow_duplicate": True})

    assert second.status_code == 409 and second.json()["detail"]["document"]["id"] == first["id"]
    assert other.status_code == 201 and confirmed.status_code == 201


async def test_a_file_attached_twice_to_a_conversation_is_not_refused(client):
    from app.models.conversation import Conversation

    async with async_session_factory() as session:
        conversation = Conversation(user_id="dev-user")
        session.add(conversation)
        await session.commit()
        conversation_id = conversation.id

    responses = [
        await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("report.pdf", PDF, "application/pdf")},
        )
        for _ in range(2)
    ]

    assert [response.status_code for response in responses] == [201, 201]


async def test_a_living_document_has_the_hash_of_its_file(client):
    collection_id = await _collection(client)

    response = await client.post(
        f"/api/collections/{collection_id}/documents/living",
        files={"file": ("notes.md", b"# Notes", "text/markdown")},
    )

    assert response.status_code == 201
    assert await _hash_of(response.json()["id"]) == hashlib.sha256(b"# Notes").hexdigest()


async def test_replacing_the_file_of_a_document_forgets_its_hash_until_the_new_one_is_known(client):
    from app.repositories.document_repository import DocumentRepository

    collection_id = await _collection(client)
    document_id = (await _upload(client, collection_id)).json()["id"]

    async with async_session_factory() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        await DocumentRepository(session).set_current_file(document, "documents/x/new.pdf")
        await session.commit()

    assert await _hash_of(document_id) is None


async def test_the_hash_is_not_part_of_what_a_user_sees_of_a_document(client):
    collection_id = await _collection(client)
    document_id = (await _upload(client, collection_id)).json()["id"]

    listed = (await client.get(f"/api/collections/{collection_id}/documents")).json()[0]
    detail = (await client.get(f"/api/collections/{collection_id}/documents/{document_id}")).json()

    for shown in (listed, detail):
        assert PDF_HASH not in str(shown) and "content_hash" not in shown
