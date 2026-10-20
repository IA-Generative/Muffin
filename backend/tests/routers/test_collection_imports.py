"""ZIP import (#223): the backend half - upload, root collection, and the routes the worker uses."""

import io
import uuid
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.collection_import import CollectionImport, CollectionImportStatus
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.run import Run
from app.models.task import Task
from app.services import collection_import_service
from tests.routers.test_collections import _as_user
from tests.routers.test_internal_runs import API_KEY, _headers


@pytest.fixture
def stored(monkeypatch) -> MagicMock:
    """RustFS and Celery replaced: what was uploaded is captured, nothing leaves the process."""
    storage = MagicMock()
    storage.upload_fileobj.side_effect = lambda key, fileobj, content_type: setattr(storage, "uploaded", fileobj.read())
    monkeypatch.setattr(collection_import_service, "storage", storage)
    monkeypatch.setattr(collection_import_service, "enqueue_import_zip", lambda import_id: f"celery-{import_id}")
    monkeypatch.setattr("app.services.document_upload_service.enqueue_process_document", lambda doc_id: f"p-{doc_id}")
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)
    return storage


@pytest.fixture
async def client(stored):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(CollectionImport))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection))
        await session.commit()


def _zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a/doc.pdf", b"%PDF")
    return buffer.getvalue()


async def _import(client: AsyncClient, filename: str = "Archive RH.zip", content: bytes | None = None, **form):
    files = {"file": (filename, content if content is not None else _zip_bytes(), "application/zip")}
    return await client.post("/api/collection-imports", files=files, data={k: str(v) for k, v in form.items()})


async def _collection(client: AsyncClient, name: str, parent_id: str | None = None) -> dict:
    body = {"name": name} if parent_id is None else {"name": name, "parent_id": parent_id}
    return (await client.post("/api/collections", json=body)).json()


class TestStart:
    async def test_creates_the_root_collection_right_away_and_queues_the_import(self, client, stored):
        response = await _import(client)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        root = (await client.get(f"/api/collections/{body['root_collection_id']}")).json()
        assert root["name"] == "Archive RH"
        assert root["parent_id"] is None
        assert stored.uploaded == _zip_bytes()
        async with async_session_factory() as session:
            task = await session.scalar(select(Task).where(Task.collection_id == uuid.UUID(root["id"])))
            collection_import = await session.get(CollectionImport, uuid.UUID(body["id"]))
        assert task.celery_task_id == f"celery-{body['id']}"
        assert collection_import.archive_key == f"imports/{body['id']}.zip"

    async def test_the_same_zip_twice_at_the_same_place_gets_a_suffix(self, client):
        first = (await _import(client)).json()
        second = (await _import(client)).json()

        names = [
            (await client.get(f"/api/collections/{item['root_collection_id']}")).json()["name"]
            for item in (first, second)
        ]
        assert names == ["Archive RH", "Archive RH (2)"]

    async def test_dropped_into_a_collection_it_goes_right_under_it(self, client):
        parent = await _collection(client, "RH")
        await client.patch(f"/api/collections/{parent['id']}/settings", json={"chunk_size": 777})

        body = (await _import(client, parent_id=parent["id"])).json()

        root = (await client.get(f"/api/collections/{body['root_collection_id']}")).json()
        assert root["parent_id"] == parent["id"]
        assert root["chunking_settings"]["chunk_size"] == 777

    async def test_a_name_taken_elsewhere_in_the_tree_needs_no_suffix(self, client):
        parent = await _collection(client, "RH")
        await _import(client)

        body = (await _import(client, parent_id=parent["id"])).json()

        assert (await client.get(f"/api/collections/{body['root_collection_id']}")).json()["name"] == "Archive RH"

    @pytest.mark.parametrize(
        ("filename", "content"), [("notes.txt", b"hello"), ("fake.zip", b"not a zip"), ("archive.zip", b"")]
    )
    async def test_anything_but_a_zip_is_refused_before_creating_anything(self, client, stored, filename, content):
        response = await _import(client, filename=filename, content=content)

        assert response.status_code == 422
        assert (await client.get("/api/collections")).json()["total"] == 0
        stored.upload_fileobj.assert_not_called()

    async def test_an_archive_over_the_upload_limit_is_refused(self, client, monkeypatch):
        monkeypatch.setattr(collection_import_service._document_settings, "ZIP_IMPORT_MAX_UPLOAD_BYTES", 10)

        assert (await _import(client)).status_code == 413

    async def test_a_parent_the_user_does_not_own_is_a_404(self, client):
        app.dependency_overrides[get_current_user] = _as_user("someone-else", "else@example.com")
        theirs = await _collection(client, "Theirs")
        app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")

        assert (await _import(client, parent_id=theirs["id"])).status_code == 404

    async def test_a_conversation_of_someone_else_is_a_404(self, client):
        async with async_session_factory() as session:
            conversation = Conversation(user_id="someone-else")
            session.add(conversation)
            await session.commit()

        assert (await _import(client, conversation_id=conversation.id)).status_code == 404

    async def test_both_a_parent_and_a_conversation_is_refused(self, client):
        parent = await _collection(client, "RH")

        response = await _import(client, parent_id=parent["id"], conversation_id=uuid.uuid4())

        assert response.status_code == 422

    async def test_only_its_owner_can_follow_an_import(self, client):
        body = (await _import(client)).json()

        app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")

        assert (await client.get(f"/api/collection-imports/{body['id']}")).status_code == 404


class TestConversation:
    async def _conversation(self, user_id: str = "owner") -> uuid.UUID:
        async with async_session_factory() as session:
            conversation = Conversation(user_id=user_id)
            session.add(conversation)
            await session.commit()
            return conversation.id

    async def test_its_runs_pin_the_imported_collection_and_its_sub_collections(self, client):
        conversation_id = await self._conversation()
        body = (await _import(client, conversation_id=conversation_id)).json()
        child = await _collection(client, "Sous-dossier", body["root_collection_id"])

        with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run"):
            run = (await client.post("/api/runs", json={"query": "q", "conversation_id": str(conversation_id)})).json()

        async with async_session_factory() as session:
            pinned = (await session.get(Run, uuid.UUID(run["id"]))).pinned_collection_ids
        assert set(pinned) == {body["root_collection_id"], child["id"]}

    async def test_deleting_the_conversation_keeps_the_collection(self, client):
        conversation_id = await self._conversation()
        body = (await _import(client, conversation_id=conversation_id)).json()

        async with async_session_factory() as session:
            await session.delete(await session.get(Conversation, conversation_id))
            await session.commit()

        assert (await client.get(f"/api/collections/{body['root_collection_id']}")).status_code == 200
        assert (await client.get(f"/api/collection-imports/{body['id']}")).json()["conversation_id"] is None


class TestWorkerRoutes:
    async def test_begin_marks_it_running_and_hands_over_the_archive(self, client):
        body = (await _import(client)).json()

        response = await client.post(f"/api/internal/collection-imports/{body['id']}/begin", headers=_headers())

        assert response.json()["archive_key"] == f"imports/{body['id']}.zip"
        assert response.json()["root_collection_id"] == body["root_collection_id"]
        assert (await client.get(f"/api/collection-imports/{body['id']}")).json()["status"] == "running"

    async def test_a_folder_becomes_a_sub_collection_with_its_parent_settings(self, client):
        body = (await _import(client)).json()
        await client.patch(f"/api/collections/{body['root_collection_id']}/settings", json={"chunk_size": 321})

        created = await client.post(
            f"/api/internal/collection-imports/{body['id']}/collections",
            headers=_headers(),
            json={"parent_id": body["root_collection_id"], "name": "Congés"},
        )

        child = (await client.get(f"/api/collections/{created.json()['id']}")).json()
        assert child["parent_id"] == body["root_collection_id"]
        assert child["chunking_settings"]["chunk_size"] == 321

    async def test_the_worker_cannot_write_into_another_owners_collection(self, client):
        body = (await _import(client)).json()
        app.dependency_overrides[get_current_user] = _as_user("someone-else", "else@example.com")
        theirs = await _collection(client, "Theirs")

        to_collection = await client.post(
            f"/api/internal/collection-imports/{body['id']}/collections",
            headers=_headers(),
            json={"parent_id": theirs["id"], "name": "x"},
        )
        to_document = await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents",
            headers=_headers(),
            json={"collection_id": theirs["id"], "name": "x.pdf", "storage_key": f"documents/{theirs['id']}/x.pdf"},
        )

        assert to_collection.status_code == 409 and to_document.status_code == 409

    async def test_a_document_is_recorded_for_the_uploader_and_queued(self, client):
        body = (await _import(client)).json()
        root_id = body["root_collection_id"]

        response = await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents",
            headers=_headers(),
            json={"collection_id": root_id, "name": "doc.pdf", "storage_key": f"documents/{root_id}/abc-doc.pdf"},
        )

        async with async_session_factory() as session:
            document = await session.get(Document, uuid.UUID(response.json()["id"]))
            task = await session.scalar(select(Task).where(Task.document_id == document.id))
        assert document.name == "doc.pdf" and document.added_by_user_id == "owner"
        assert task.celery_task_id == f"p-{document.id}"

    async def test_a_storage_key_outside_the_collection_is_refused(self, client):
        body = (await _import(client)).json()

        response = await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents",
            headers=_headers(),
            json={"collection_id": body["root_collection_id"], "name": "x.pdf", "storage_key": "documents/other/x.pdf"},
        )

        assert response.status_code == 409

    async def test_the_result_is_stored_and_the_archive_deleted(self, client, stored):
        body = (await _import(client)).json()
        summary = {"collections_created": 1, "documents_created": 2, "skipped": [{"path": "a.exe", "reason": "x"}]}

        await client.put(
            f"/api/internal/collection-imports/{body['id']}/result",
            headers=_headers(),
            json={"status": "completed", "summary": summary},
        )

        out = (await client.get(f"/api/collection-imports/{body['id']}")).json()
        assert out["status"] == "completed" and out["summary"] == summary
        stored.delete_objects.assert_called_once_with([f"imports/{body['id']}.zip"])
        async with async_session_factory() as session:
            collection_import = await session.get(CollectionImport, uuid.UUID(body["id"]))
        assert collection_import.archive_key is None
        assert collection_import.status == CollectionImportStatus.COMPLETED
