import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.task import Task

SERVICE = "app.services.living_document_service"
ODT = "application/vnd.oasis.opendocument.text"


@pytest.fixture
async def client():
    # See tests/routers/test_collections.py for why this isn't the sync TestClient.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Collection))
        await session.commit()


@contextmanager
def _mocked_io():
    with (
        patch(f"{SERVICE}.storage.put_object") as put,
        patch(f"{SERVICE}.storage.delete_objects") as delete_objects,
        patch(f"{SERVICE}.vector_store.delete_document_embeddings") as delete_vectors,
        patch(f"{SERVICE}.enqueue_process_document", side_effect=lambda _id: str(uuid.uuid4())) as enqueue,
    ):
        yield {"put": put, "delete_objects": delete_objects, "delete_vectors": delete_vectors, "enqueue": enqueue}


async def _create_collection(client) -> str:
    return (await client.post("/api/collections")).json()["id"]


async def _create_living(client, collection_id: str, filename: str = "procedure.odt") -> dict:
    with _mocked_io():
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living",
            files={"file": (filename, b"v1", ODT)},
        )
    assert response.status_code == 201
    return response.json()


async def test_create_living_document_stores_first_revision_and_queues_processing(client):
    collection_id = await _create_collection(client)

    with _mocked_io() as io:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living",
            files={"file": ("procedure.odt", b"v1", ODT)},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "living"
    assert body["type"] == "file"
    assert body["status"] == "pending"
    io["put"].assert_called_once()
    io["enqueue"].assert_called_once_with(body["id"])

    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{body['id']}/revisions")).json()
    assert len(revisions) == 1
    assert revisions[0]["number"] == 1
    assert revisions[0]["format"] == "odt"
    assert revisions[0]["origin"] == "upload"
    assert revisions[0]["is_current"] is True

    detail = (await client.get(f"/api/collections/{collection_id}/documents/{body['id']}")).json()
    assert detail["kind"] == "living"
    assert detail["current_revision"] == 1


async def test_create_living_document_accepts_markdown(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id, "notes.md")
    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")).json()
    assert revisions[0]["format"] == "md"


async def test_create_living_document_rejects_other_formats(client):
    collection_id = await _create_collection(client)
    with _mocked_io() as io:
        response = await client.post(
            f"/api/collections/{collection_id}/documents/living",
            files={"file": ("report.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 415
    io["put"].assert_not_called()
    assert (await client.get(f"/api/collections/{collection_id}/documents")).json() == []


async def test_replace_appends_a_revision_and_reindexes_that_document_only(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)

    with _mocked_io() as io:
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            files={"file": ("procedure-v2.odt", b"v2", ODT)},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    io["delete_vectors"].assert_called_once()
    assert str(io["delete_vectors"].call_args.args[1]) == created["id"]
    io["enqueue"].assert_called_once_with(created["id"])

    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")).json()
    assert [(r["number"], r["filename"], r["is_current"]) for r in revisions] == [
        (2, "procedure-v2.odt", True),
        (1, "procedure.odt", False),
    ]
    # The document keeps its identity and name across revisions.
    detail = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}")).json()
    assert detail["id"] == created["id"]
    assert detail["name"] == "procedure.odt"
    assert detail["current_revision"] == 2


async def test_replace_rejects_a_different_format(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io() as io:
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            files={"file": ("procedure.md", b"# v2", "text/markdown")},
        )
    assert response.status_code == 422
    io["put"].assert_not_called()
    io["enqueue"].assert_not_called()


async def test_replace_on_a_standard_document_returns_409(client):
    collection_id = await _create_collection(client)
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="task-id"),
    ):
        standard = (
            await client.post(
                f"/api/collections/{collection_id}/documents/file",
                files={"file": ("plain.odt", b"data", ODT)},
            )
        ).json()
    assert standard["kind"] == "standard"

    with _mocked_io():
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{standard['id']}/content",
            files={"file": ("plain.odt", b"data2", ODT)},
        )
        revisions = await client.get(f"/api/collections/{collection_id}/documents/{standard['id']}/revisions")
    assert response.status_code == 409
    assert revisions.status_code == 409


async def test_restore_appends_a_revision_pointing_at_the_old_file(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            files={"file": ("procedure-v2.odt", b"v2", ODT)},
        )

    with _mocked_io() as io:
        response = await client.post(f"/api/collections/{collection_id}/documents/{created['id']}/revisions/1/restore")

    assert response.status_code == 200
    # Restoring re-uses revision 1's file: nothing new is uploaded, but the document is reprocessed.
    io["put"].assert_not_called()
    io["enqueue"].assert_called_once_with(created["id"])
    revisions = (await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")).json()
    assert [r["number"] for r in revisions] == [3, 2, 1]
    assert revisions[0]["origin"] == "restore"
    assert revisions[0]["restored_from_number"] == 1
    assert revisions[0]["filename"] == "procedure.odt"
    assert revisions[0]["is_current"] is True


async def test_restore_unknown_revision_returns_404(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        response = await client.post(f"/api/collections/{collection_id}/documents/{created['id']}/revisions/9/restore")
    assert response.status_code == 404


async def test_unknown_document_returns_404(client):
    collection_id = await _create_collection(client)
    with _mocked_io():
        response = await client.put(
            f"/api/collections/{collection_id}/documents/{uuid.uuid4()}/content",
            files={"file": ("a.odt", b"x", ODT)},
        )
    assert response.status_code == 404


async def test_deleting_a_living_document_removes_every_revision_file(client):
    collection_id = await _create_collection(client)
    created = await _create_living(client, collection_id)
    with _mocked_io():
        await client.put(
            f"/api/collections/{collection_id}/documents/{created['id']}/content",
            files={"file": ("procedure-v2.odt", b"v2", ODT)},
        )

    with (
        patch("app.services.document_upload_service.storage.delete_objects") as mock_delete,
        patch("app.services.document_upload_service.vector_store.delete_document_embeddings"),
    ):
        response = await client.delete(f"/api/collections/{collection_id}/documents/{created['id']}")

    assert response.status_code == 204
    (deleted_keys,), _ = mock_delete.call_args
    assert len(deleted_keys) == 2
    assert any(key.endswith("procedure.odt") for key in deleted_keys)
    assert any(key.endswith("procedure-v2.odt") for key in deleted_keys)


async def test_only_the_collection_owner_can_use_living_documents(client):
    def _as_user(user_id: str):
        def override() -> RequestContext:
            return RequestContext(user_id=user_id, email=f"{user_id}@example.com", roles=["user"], is_admin=False)

        return override

    app.dependency_overrides[get_current_user] = _as_user("user-a")
    try:
        collection_id = await _create_collection(client)
        created = await _create_living(client, collection_id)

        app.dependency_overrides[get_current_user] = _as_user("user-b")
        with _mocked_io():
            replace = await client.put(
                f"/api/collections/{collection_id}/documents/{created['id']}/content",
                files={"file": ("procedure.odt", b"x", ODT)},
            )
            listing = await client.get(f"/api/collections/{collection_id}/documents/{created['id']}/revisions")
        assert replace.status_code == 404
        assert listing.status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]
