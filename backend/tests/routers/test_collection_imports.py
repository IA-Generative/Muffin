"""ZIP import (#223): the backend half - upload, root collection, and the routes the worker uses."""

import asyncio
import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.collection_import import CollectionImport, CollectionImportStatus
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.import_document import ImportDocument
from app.models.run import Run
from app.models.task import Task
from app.services import collection_import_service, import_processing_queue
from tests.routers.test_collections import _as_user
from tests.routers.test_internal_runs import API_KEY, _headers

# SHA-256 of a file of the archive, as the worker computes it as it reads the member (#300).
HASH = "a" * 64


@pytest.fixture
def stored(monkeypatch) -> MagicMock:
    """RustFS and Celery replaced: what was uploaded is captured, nothing leaves the process."""
    storage = MagicMock()
    storage.upload_fileobj.side_effect = lambda key, fileobj, content_type: setattr(storage, "uploaded", fileobj.read())
    monkeypatch.setattr(collection_import_service, "storage", storage)
    monkeypatch.setattr(
        collection_import_service, "enqueue_import_zip", lambda import_id, task_id=None: f"celery-{import_id}"
    )
    storage.queued = []
    seen: set[str] = set()

    def enqueue(doc_id, bulk=False, task_id=None):
        storage.queued.append(doc_id)
        # One id per call, like Celery's: a document processed again gets a task of its own.
        suffix = f"-{uuid.uuid4()}" if doc_id in seen else ""
        seen.add(doc_id)
        return f"p-{doc_id}{'-bulk' if bulk else ''}{suffix}"

    monkeypatch.setattr("app.services.document_upload_service.enqueue_process_document", enqueue)
    # The documents of an import are queued by its window (#335).
    monkeypatch.setattr("app.services.import_processing_queue.enqueue_process_document", enqueue)
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
    """The same bytes at every call: a fixed date for the entry, which writestr would otherwise stamp with
    the current time - two calls on either side of a (2 s, in a ZIP) tick would differ."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("a/doc.pdf", date_time=(2026, 1, 1, 0, 0, 0)), b"%PDF")
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
            json={
                "collection_id": theirs["id"],
                "name": "x.pdf",
                "storage_key": f"documents/{theirs['id']}/x.pdf",
                "content_hash": HASH,
            },
        )

        assert to_collection.status_code == 409 and to_document.status_code == 409

    async def test_a_document_is_recorded_for_the_uploader_and_queued(self, client):
        body = (await _import(client)).json()
        root_id = body["root_collection_id"]

        response = await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents",
            headers=_headers(),
            json={
                "collection_id": root_id,
                "name": "doc.pdf",
                "storage_key": f"documents/{root_id}/abc-doc.pdf",
                "content_hash": HASH,
            },
        )

        async with async_session_factory() as session:
            document = await session.get(Document, uuid.UUID(response.json()["id"]))
            task = await session.scalar(select(Task).where(Task.document_id == document.id))
        assert document.name == "doc.pdf" and document.added_by_user_id == "owner"
        # The hash the worker computed as it read the member (#300).
        assert document.content_hash == HASH
        # Queued behind any document someone dropped by hand (#291).
        assert task.celery_task_id == f"p-{document.id}-bulk"

    async def test_a_file_already_in_the_collection_is_reported_as_a_duplicate_before_it_is_stored(self, client):
        body = (await _import(client)).json()
        root_id = body["root_collection_id"]
        check = f"/api/internal/collection-imports/{body['id']}/documents/check"
        assert (
            await client.post(check, headers=_headers(), json={"collection_id": root_id, "content_hash": HASH})
        ).json() == {"duplicate": False}

        await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents",
            headers=_headers(),
            json={
                "collection_id": root_id,
                "name": "doc.pdf",
                "storage_key": f"documents/{root_id}/abc-doc.pdf",
                "content_hash": HASH,
            },
        )

        # The same file, in the same archive or another: it is there now.
        assert (
            await client.post(check, headers=_headers(), json={"collection_id": root_id, "content_hash": HASH})
        ).json() == {"duplicate": True}
        other = "b" * 64
        assert (
            await client.post(check, headers=_headers(), json={"collection_id": root_id, "content_hash": other})
        ).json() == {"duplicate": False}

    async def test_the_duplicate_check_is_for_the_imports_own_collections(self, client):
        body = (await _import(client)).json()
        app.dependency_overrides[get_current_user] = _as_user("someone-else", "else@example.com")
        theirs = await _collection(client, "Theirs")

        response = await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents/check",
            headers=_headers(),
            json={"collection_id": theirs["id"], "content_hash": HASH},
        )

        assert response.status_code == 409

    async def test_a_storage_key_outside_the_collection_is_refused(self, client):
        body = (await _import(client)).json()

        response = await client.post(
            f"/api/internal/collection-imports/{body['id']}/documents",
            headers=_headers(),
            json={
                "collection_id": body["root_collection_id"],
                "name": "x.pdf",
                "storage_key": "documents/other/x.pdf",
                "content_hash": HASH,
            },
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
        # The archive, and the plan of a big import (#334) stored beside it.
        stored.delete_objects.assert_called_once_with(
            [f"imports/{body['id']}.zip", f"imports/{body['id']}.zip.plan.json"]
        )
        async with async_session_factory() as session:
            collection_import = await session.get(CollectionImport, uuid.UUID(body["id"]))
        assert collection_import.archive_key is None
        assert collection_import.status == CollectionImportStatus.COMPLETED


class TestAttachSuggestion:
    @pytest.fixture
    def search(self, monkeypatch) -> MagicMock:
        """The embedding model and the collections index replaced; returns the index search."""
        import fakeredis

        from app.services import description_rollup_service

        async def model(_db):
            return "embedder"

        async def embed(_model, _text):
            return [0.1, 0.2]

        search = MagicMock(return_value=[])
        monkeypatch.setattr(collection_import_service, "default_embedding_model", model)
        monkeypatch.setattr(collection_import_service, "embed_text", embed)
        monkeypatch.setattr(collection_import_service.vector_store, "search_collections", search)
        monkeypatch.setattr(description_rollup_service, "_redis", fakeredis.FakeRedis(decode_responses=True))
        monkeypatch.setattr(description_rollup_service, "enqueue_rollup_collection_description", lambda *_: "r")
        return search

    async def _conversation(self) -> uuid.UUID:
        async with async_session_factory() as session:
            conversation = Conversation(user_id="owner")
            session.add(conversation)
            await session.commit()
            return conversation.id

    async def _describe(self, client: AsyncClient, collection_id: str, description: str) -> None:
        """What the pipeline does once the collection's documents are summarized."""
        response = await client.patch(
            f"/api/internal/collections/{collection_id}/description",
            headers=_headers(),
            json={"description": description},
        )
        assert response.status_code == 200

    async def _suggested(self, client: AsyncClient, search: MagicMock, target: dict) -> dict:
        """An import dropped into a conversation, with `target` suggested once it's described."""
        body = (await _import(client, conversation_id=await self._conversation())).json()
        search.return_value = [(uuid.UUID(target["id"]), 0.87)]
        await self._describe(client, body["root_collection_id"], "Politiques RH.")
        return body

    async def test_waits_for_a_description_before_suggesting(self, client, search):
        body = (await _import(client, conversation_id=await self._conversation())).json()

        assert body["attach_status"] == "pending"
        assert body["attach_candidates"] == []
        search.assert_not_called()

    async def test_suggests_an_owned_collection_never_itself_nor_below_it(self, client, search):
        target = await _collection(client, "Ressources humaines")
        body = (await _import(client, conversation_id=await self._conversation())).json()
        child = await _collection(client, "Sous-dossier", body["root_collection_id"])
        search.return_value = [(uuid.UUID(target["id"]), 0.87)]

        await self._describe(client, body["root_collection_id"], "Politiques RH.")

        searched_ids = {str(cid) for cid in search.call_args.args[2]}
        assert target["id"] in searched_ids
        assert body["root_collection_id"] not in searched_ids and child["id"] not in searched_ids
        out = (await client.get(f"/api/collection-imports/{body['id']}")).json()
        assert out["attach_candidates"][0]["collection_id"] == target["id"]
        assert out["attach_candidates"][0]["score"] == 0.87
        assert out["root_collection_name"] == "Archive RH"

    async def test_awaiting_imports_are_listed_until_answered(self, client, search):
        target = await _collection(client, "RH")
        body = await self._suggested(client, search, target)

        awaiting = (await client.get("/api/collection-imports", params={"awaiting_attachment": "true"})).json()
        assert [item["id"] for item in awaiting] == [body["id"]]

        await client.post(f"/api/collection-imports/{body['id']}/attach", json={"action": "accept"})

        assert (await client.get("/api/collection-imports", params={"awaiting_attachment": "true"})).json() == []

    async def test_accepting_moves_the_collection_under_the_suggestion(self, client, search):
        target = await _collection(client, "RH")
        body = await self._suggested(client, search, target)

        out = (await client.post(f"/api/collection-imports/{body['id']}/attach", json={"action": "accept"})).json()

        assert out["attach_status"] == "attached"
        root = (await client.get(f"/api/collections/{body['root_collection_id']}")).json()
        assert root["parent_id"] == target["id"]

    async def test_choosing_another_collection_moves_it_there(self, client, search):
        suggested = await _collection(client, "RH")
        chosen = await _collection(client, "Juridique")
        body = await self._suggested(client, search, suggested)

        await client.post(
            f"/api/collection-imports/{body['id']}/attach",
            json={"action": "choose_other", "target_collection_id": chosen["id"]},
        )

        assert (await client.get(f"/api/collections/{body['root_collection_id']}")).json()["parent_id"] == chosen["id"]

    async def test_a_foreign_target_or_one_below_it_is_refused(self, client, search):
        target = await _collection(client, "RH")
        body = await self._suggested(client, search, target)
        below = await _collection(client, "Dedans", body["root_collection_id"])
        app.dependency_overrides[get_current_user] = _as_user("someone-else", "else@example.com")
        theirs = await _collection(client, "Theirs")
        app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com")

        foreign = await client.post(
            f"/api/collection-imports/{body['id']}/attach",
            json={"action": "choose_other", "target_collection_id": theirs["id"]},
        )
        cycle = await client.post(
            f"/api/collection-imports/{body['id']}/attach",
            json={"action": "choose_other", "target_collection_id": below["id"]},
        )

        assert foreign.status_code == 404 and cycle.status_code == 409
        assert (await client.get(f"/api/collections/{body['root_collection_id']}")).json()["parent_id"] is None

    async def test_dismissing_keeps_it_at_the_top_and_stops_suggesting(self, client, search):
        target = await _collection(client, "RH")
        body = await self._suggested(client, search, target)

        out = (await client.post(f"/api/collection-imports/{body['id']}/attach", json={"action": "dismiss"})).json()
        search.reset_mock()
        await self._describe(client, body["root_collection_id"], "Description mise à jour.")

        assert out["attach_status"] == "dismissed"
        search.assert_not_called()
        assert (await client.get(f"/api/collections/{body['root_collection_id']}")).json()["parent_id"] is None

    async def test_an_import_dropped_into_a_collection_gets_no_suggestion(self, client, search):
        parent = await _collection(client, "RH")
        body = (await _import(client, parent_id=parent["id"])).json()

        await self._describe(client, body["root_collection_id"], "Politiques RH.")
        response = await client.post(f"/api/collection-imports/{body['id']}/attach", json={"action": "dismiss"})

        assert body["attach_status"] == "not_applicable"
        search.assert_not_called()
        assert response.status_code == 422

    async def test_accept_without_a_suggestion_yet_is_refused(self, client, search):
        body = (await _import(client, conversation_id=await self._conversation())).json()

        response = await client.post(f"/api/collection-imports/{body['id']}/attach", json={"action": "accept"})

        assert response.status_code == 422

    async def test_list_by_conversation(self, client, search):
        conversation_id = await self._conversation()
        mine = (await _import(client, conversation_id=conversation_id)).json()
        await _import(client)

        listed = (await client.get("/api/collection-imports", params={"conversation_id": str(conversation_id)})).json()

        assert [item["id"] for item in listed] == [mine["id"]]


# --- The window of an import's extractions (#335) ---


@pytest.fixture
def _window(monkeypatch):
    monkeypatch.setattr(import_processing_queue._settings, "IMPORT_PROCESSING_WINDOW", 3)


async def _add(client, import_body: dict, count: int) -> list[str]:
    """`count` documents registered by the worker, one after the other, as it stores the archive's files."""
    root_id, ids = import_body["root_collection_id"], []
    for number in range(count):
        response = await client.post(
            f"/api/internal/collection-imports/{import_body['id']}/documents",
            headers=_headers(),
            json={
                "collection_id": root_id,
                "name": f"doc-{number}.pdf",
                "storage_key": f"documents/{root_id}/{uuid.uuid4()}-doc-{number}.pdf",
                "content_hash": f"{number:064x}",
            },
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return ids


async def _entries(import_id: str) -> list[ImportDocument]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(ImportDocument)
            .where(ImportDocument.import_id == uuid.UUID(import_id))
            .order_by(ImportDocument.created_at, ImportDocument.document_id)
        )
        return list(result.scalars())


async def _extraction_done(client, document_id: str):
    response = await client.post(f"/api/internal/documents/{document_id}/extraction-done", headers=_headers())
    assert response.status_code == 200, response.text


async def test_only_a_window_of_the_documents_of_an_import_is_queued(client, stored, _window):
    body = (await _import(client)).json()

    ids = await _add(client, body, 10)

    assert stored.queued == ids[:3]
    assert [entry.released_at is not None for entry in await _entries(body["id"])] == [True] * 3 + [False] * 7
    async with async_session_factory() as session:
        # A document that waits has no task yet: it is queued, with the low priority of an import, later.
        tasks = (await session.scalars(select(Task.celery_task_id).where(Task.document_id.is_not(None)))).all()
    assert sorted(tasks) == sorted(f"p-{document_id}-bulk" for document_id in ids[:3])


async def test_the_end_of_an_extraction_releases_the_next_document_of_its_import(client, stored, _window):
    body = (await _import(client)).json()
    ids = await _add(client, body, 6)

    await _extraction_done(client, ids[0])

    assert stored.queued == ids[:4]
    # Said again - a task run twice - it frees nothing more.
    await _extraction_done(client, ids[0])
    assert stored.queued == ids[:4]


async def test_the_ends_of_two_extractions_at_the_same_time_release_two_different_documents(client, stored, _window):
    body = (await _import(client)).json()
    ids = await _add(client, body, 8)

    await asyncio.gather(*(_extraction_done(client, document_id) for document_id in ids[:3]))

    assert stored.queued == ids[:6] or sorted(stored.queued) == sorted(ids[:6])
    assert len(set(stored.queued)) == len(stored.queued) == 6


async def test_the_end_of_a_document_that_is_not_of_an_import_does_nothing(client, stored, _window):
    await _extraction_done(client, str(uuid.uuid4()))

    assert stored.queued == []


async def test_a_document_that_fails_gives_its_place_to_the_next(client, stored, _window):
    body = (await _import(client)).json()
    ids = await _add(client, body, 5)

    response = await client.patch(
        f"/api/internal/documents/{ids[1]}/status", headers=_headers(), json={"status": "error"}
    )

    assert response.status_code == 200
    assert stored.queued == ids[:4]


async def test_a_document_whose_error_is_reported_gives_its_place_to_the_next(client, stored, _window):
    body = (await _import(client)).json()
    ids = await _add(client, body, 5)

    await client.patch(f"/api/internal/documents/{ids[0]}/error", headers=_headers(), json={"error": "boom"})

    assert stored.queued == ids[:4]


async def test_a_document_deleted_while_it_is_extracted_gives_its_place_to_the_next(
    client, stored, _window, monkeypatch
):
    monkeypatch.setattr("app.services.document_upload_service.vector_store", MagicMock())
    monkeypatch.setattr("app.services.document_upload_service.storage", MagicMock())
    body = (await _import(client)).json()
    ids = await _add(client, body, 5)

    response = await client.delete(f"/api/collections/{body['root_collection_id']}/documents/{ids[0]}")

    assert response.status_code == 204
    assert stored.queued == ids[:4]


async def test_a_document_deleted_while_it_waits_takes_nobody_s_place(client, stored, _window, monkeypatch):
    monkeypatch.setattr("app.services.document_upload_service.vector_store", MagicMock())
    monkeypatch.setattr("app.services.document_upload_service.storage", MagicMock())
    body = (await _import(client)).json()
    ids = await _add(client, body, 5)

    await client.delete(f"/api/collections/{body['root_collection_id']}/documents/{ids[4]}")

    assert stored.queued == ids[:3]
    assert len(await _entries(body["id"])) == 4


async def test_two_imports_each_have_their_own_window(client, stored, _window):
    first, second = (await _import(client)).json(), (await _import(client, "Autre.zip")).json()

    first_ids, second_ids = await _add(client, first, 6), await _add(client, second, 6)

    assert sorted(stored.queued) == sorted(first_ids[:3] + second_ids[:3])


async def test_the_sweep_releases_the_place_of_a_document_that_was_lost(client, stored, _window):
    body = (await _import(client)).json()
    ids = await _add(client, body, 5)
    assert (await client.post("/api/internal/collection-imports/release", headers=_headers())).json() == {"released": 0}
    # Its task never ran, and the window is full of such documents: past the delay, they stop holding it.
    stale = datetime.now(UTC) - timedelta(seconds=import_processing_queue._settings.IMPORT_SLOT_TIMEOUT_SECONDS + 60)
    async with async_session_factory() as session:
        await session.execute(
            update(ImportDocument).where(ImportDocument.document_id == uuid.UUID(ids[0])).values(released_at=stale)
        )
        await session.commit()

    response = await client.post("/api/internal/collection-imports/release", headers=_headers())

    assert response.json() == {"released": 1}
    assert stored.queued == ids[:4]


async def test_a_document_that_could_not_be_queued_waits_again(client, stored, _window, monkeypatch):
    body = (await _import(client)).json()

    def broken(document_id, bulk=False, task_id=None):
        raise ConnectionError("Redis is down")

    monkeypatch.setattr("app.services.import_processing_queue.enqueue_process_document", broken)
    with pytest.raises(ConnectionError):
        await _add(client, body, 1)

    entries = await _entries(body["id"])
    assert len(entries) == 1 and entries[0].released_at is None


# --- A big archive read in batches of files (#334) ---


class TestBatches:
    async def _begin(self, client, import_id: str, expected: list[str]):
        plan = {"collections_created": 2, "skipped": [{"path": "run.exe", "reason": "type"}]}
        response = await client.post(
            f"/api/internal/collection-imports/{import_id}/batches/begin",
            headers=_headers(),
            json={"expected": expected, "plan": plan},
        )
        assert response.status_code == 200, response.text

    async def _done(self, client, import_id: str, key: str, created: int = 0, skipped=()):
        response = await client.post(
            f"/api/internal/collection-imports/{import_id}/batches/{key}/done",
            headers=_headers(),
            json={"documents_created": created, "skipped": list(skipped)},
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def test_a_batch_says_where_the_import_is_and_the_last_one_gets_the_summary_of_all(self, client):
        body = (await _import(client)).json()
        await client.get(f"/api/collection-imports/{body['id']}")
        await client.post(f"/api/internal/collection-imports/{body['id']}/begin", headers=_headers())
        await self._begin(client, body["id"], ["batch:0", "batch:1", "batch:2"])

        first = await self._done(
            client, body["id"], "batch:1", created=5, skipped=[{"path": "b.pdf", "reason": "doublon"}]
        )
        second = await self._done(client, body["id"], "batch:0", created=3)
        last = await self._done(client, body["id"], "batch:2", created=4)

        assert first == {"status": "running", "done": 1, "expected": 3, "completed_now": False, "summary": None}
        assert second["done"] == 2 and not second["completed_now"]
        assert last["completed_now"] and last["done"] == 3
        # The planner's part, then each batch's in the order they were announced - whichever finished first.
        assert last["summary"] == {
            "collections_created": 2,
            "documents_created": 12,
            "skipped": [{"path": "run.exe", "reason": "type"}, {"path": "b.pdf", "reason": "doublon"}],
        }

    async def test_a_batch_that_runs_again_counts_once_as_what_it_first_reported(self, client):
        body = (await _import(client)).json()
        await client.post(f"/api/internal/collection-imports/{body['id']}/begin", headers=_headers())
        await self._begin(client, body["id"], ["batch:0", "batch:1"])
        await self._done(client, body["id"], "batch:0", created=3)

        # Its files are registered by now: read again, they are duplicates.
        again = await self._done(
            client, body["id"], "batch:0", created=0, skipped=[{"path": "a.pdf", "reason": "doublon"}]
        )
        last = await self._done(client, body["id"], "batch:1", created=1)

        assert again["done"] == 1 and not again["completed_now"]
        assert last["summary"]["documents_created"] == 4 and len(last["summary"]["skipped"]) == 1

    async def test_the_batches_finishing_at_the_same_time_complete_the_import_once(self, client):
        body = (await _import(client)).json()
        await client.post(f"/api/internal/collection-imports/{body['id']}/begin", headers=_headers())
        keys = [f"batch:{number}" for number in range(6)]
        await self._begin(client, body["id"], keys)

        results = await asyncio.gather(*(self._done(client, body["id"], key, created=1) for key in keys))

        assert sum(result["completed_now"] for result in results) == 1
        assert max(result["done"] for result in results) == 6

    async def test_a_failure_keeps_what_the_batches_reported_and_what_the_failed_one_had_done(self, client):
        body = (await _import(client)).json()
        await client.post(f"/api/internal/collection-imports/{body['id']}/begin", headers=_headers())
        await self._begin(client, body["id"], ["batch:0", "batch:1"])
        await self._done(client, body["id"], "batch:0", created=3)

        await client.put(
            f"/api/internal/collection-imports/{body['id']}/result",
            headers=_headers(),
            json={
                "status": "failed",
                "summary": {"documents_created": 2, "skipped": [{"path": "c.pdf", "reason": "corrompu"}]},
                "error": "boom",
            },
        )

        out = (await client.get(f"/api/collection-imports/{body['id']}")).json()
        assert out["status"] == "failed" and out["error"] == "boom"
        assert out["summary"] == {
            "collections_created": 2,
            "documents_created": 5,
            "skipped": [{"path": "run.exe", "reason": "type"}, {"path": "c.pdf", "reason": "corrompu"}],
        }
        # An import that has ended is not completed by a batch that reports after it.
        late = await self._done(client, body["id"], "batch:1", created=1)
        assert late["status"] == "failed" and not late["completed_now"]

    async def test_the_same_file_registered_twice_at_the_same_time_makes_one_document(self, client, stored):
        body = (await _import(client)).json()
        root_id = body["root_collection_id"]

        async def register(number: int):
            return await client.post(
                f"/api/internal/collection-imports/{body['id']}/documents",
                headers=_headers(),
                json={
                    "collection_id": root_id,
                    "name": "doc.pdf",
                    "storage_key": f"documents/{root_id}/{uuid.uuid4()}-doc.pdf",
                    "content_hash": HASH,
                },
            )

        responses = await asyncio.gather(*(register(number) for number in range(4)))

        bodies = [response.json() for response in responses]
        assert sum(item["id"] is not None for item in bodies) == 1
        assert sum(item["duplicate"] for item in bodies) == 3
        async with async_session_factory() as session:
            count = len((await session.scalars(select(Document).where(Document.content_hash == HASH))).all())
        assert count == 1
        # The files of the duplicates are removed from the store.
        assert stored.delete_objects.call_count == 3


# --- Relaunching the documents of an import that ended in error (#340) ---


async def test_the_documents_of_an_import_in_error_are_relaunched_through_its_window(
    client, stored, _window, monkeypatch
):
    for target in ("vector_store", "storage"):
        monkeypatch.setattr(f"app.services.document_upload_service.{target}", MagicMock())
    monkeypatch.setattr("app.services.document_upload_service.revoke_tasks", lambda ids: None)
    body = (await _import(client)).json()
    ids = await _add(client, body, 6)
    assert stored.queued == ids[:3]
    async with async_session_factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id.in_([uuid.UUID(i) for i in ids[:5]]))
            .values(status="error", error="boom")
        )
        await session.commit()
    stored.queued.clear()

    response = await client.post(f"/api/collection-imports/{body['id']}/reprocess-failed")

    assert response.json() == {"reprocessed": 5}
    # Back to waiting, like the first time: only the window is queued - the oldest first.
    assert stored.queued == ids[:3]
    entries = await _entries(body["id"])
    assert [entry.released_at is not None for entry in entries] == [True] * 3 + [False] * 3


async def test_only_the_owner_of_an_import_relaunches_its_documents(client, stored, _window):
    body = (await _import(client)).json()
    from app.core.security.factory import get_current_user as current_user

    app.dependency_overrides[current_user] = _as_user("stranger", "stranger@example.com")
    try:
        response = await client.post(f"/api/collection-imports/{body['id']}/reprocess-failed")
    finally:
        app.dependency_overrides[current_user] = _as_user("owner", "owner@example.com")

    assert response.status_code == 404
