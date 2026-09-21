import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.conversation import Conversation
from app.models.run import Run
from app.models.task import Task

WORKER_API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", WORKER_API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection))
        await session.commit()


def _as_user(user_id: str, email: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False)

    return override


async def _create_run(client, query: str = "What is the telework policy?"):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        response = await client.post("/api/runs", json={"query": query})
    return response.json()


async def _complete_run(client, run_id: str, answer: str = "Telework is allowed two days a week [abc]."):
    response = await client.patch(
        f"/api/internal/runs/{run_id}/result",
        headers={"X-API-Key": WORKER_API_KEY},
        json={"answer": answer, "citations": [{"evidence_id": "abc", "source": "policy.pdf", "vdb_id": "hr"}]},
    )
    assert response.status_code == 200


async def test_list_conversations_empty_initially(client):
    response = await client.get("/api/conversations")
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_list_conversations_returns_owned_conversations_most_recent_first(client):
    older = await _create_run(client, "What is the leave policy?")
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-2"):
        newer_response = await client.post("/api/runs", json={"query": "And telework?"})
    newer = newer_response.json()

    response = await client.get("/api/conversations")

    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [newer["conversation_id"], older["conversation_id"]]


async def test_list_conversations_scoped_to_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    await _create_run(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.get("/api/conversations")

    assert response.json()["items"] == []


async def test_list_conversation_messages_includes_user_and_assistant_turns_in_order(client):
    run = await _create_run(client, "What is the telework policy?")
    await _complete_run(client, run["id"], "Telework is allowed two days a week [abc].")

    response = await client.get(f"/api/conversations/{run['conversation_id']}/messages")

    assert response.status_code == 200
    body = response.json()
    assert [m["role"] for m in body] == ["user", "assistant"]
    assert body[0]["content"] == "What is the telework policy?"
    assert body[1]["content"] == "Telework is allowed two days a week [abc]."
    # The assistant message carries its run's id and citations - a restored message (after a
    # reload) must be able to render citation footnotes and fetch execution detail too, not just
    # a live one still held in the frontend's own memory.
    assert body[0]["run_id"] is None
    assert body[1]["run_id"] == run["id"]
    assert body[1]["citations"] == [{"evidence_id": "abc", "source": "policy.pdf", "vdb_id": "hr"}]


async def test_list_conversation_messages_accumulates_across_multiple_runs(client):
    first = await _create_run(client, "What is the telework policy?")
    await _complete_run(client, first["id"], "Two days a week [x].")

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-2"):
        second_response = await client.post(
            "/api/runs", json={"query": "And leave?", "conversation_id": first["conversation_id"]}
        )
    second = second_response.json()
    await _complete_run(client, second["id"], "25 days a year [y].")

    response = await client.get(f"/api/conversations/{first['conversation_id']}/messages")

    assert response.status_code == 200
    contents = [m["content"] for m in response.json()]
    assert contents == ["What is the telework policy?", "Two days a week [x].", "And leave?", "25 days a year [y]."]


async def test_list_conversation_messages_requires_ownership(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    run = await _create_run(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.get(f"/api/conversations/{run['conversation_id']}/messages")

    assert response.status_code == 404


async def test_list_conversation_messages_unknown_conversation_returns_404(client):
    response = await client.get(f"/api/conversations/{uuid.uuid4()}/messages")
    assert response.status_code == 404


async def test_rename_conversation(client):
    run = await _create_run(client)

    response = await client.patch(
        f"/api/conversations/{run['conversation_id']}", json={"title": "Ma conversation renommée"}
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Ma conversation renommée"

    listed = await client.get("/api/conversations")
    assert listed.json()["items"][0]["title"] == "Ma conversation renommée"


async def test_rename_conversation_locks_out_auto_titling(client):
    run = await _create_run(client)
    await client.patch(f"/api/conversations/{run['conversation_id']}", json={"title": "Mon titre"})

    title_response = await client.patch(
        f"/api/internal/conversations/{run['conversation_id']}/title",
        headers={"X-API-Key": WORKER_API_KEY},
        json={"title": "Titre auto-généré"},
    )
    assert title_response.status_code == 200

    listed = await client.get("/api/conversations")
    assert listed.json()["items"][0]["title"] == "Mon titre"


async def test_rename_conversation_requires_ownership(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    run = await _create_run(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.patch(f"/api/conversations/{run['conversation_id']}", json={"title": "x"})

    assert response.status_code == 404


async def test_rename_unknown_conversation_returns_404(client):
    response = await client.patch(f"/api/conversations/{uuid.uuid4()}", json={"title": "x"})
    assert response.status_code == 404


async def test_delete_conversation(client):
    run = await _create_run(client)

    response = await client.delete(f"/api/conversations/{run['conversation_id']}")
    assert response.status_code == 204

    listed = await client.get("/api/conversations")
    assert listed.json()["items"] == []

    async with async_session_factory() as session:
        assert await session.get(Run, uuid.UUID(run["id"])) is None


async def test_delete_conversation_requires_ownership(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    run = await _create_run(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.delete(f"/api/conversations/{run['conversation_id']}")

    assert response.status_code == 404


async def test_delete_unknown_conversation_returns_404(client):
    response = await client.delete(f"/api/conversations/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_trigger_discussion_score_enqueues_and_creates_task(client):
    run = await _create_run(client)
    await _complete_run(client, run["id"])

    with patch(
        "app.services.conversation_service.enqueue_score_discussion", return_value="celery-score-1"
    ) as mock_enqueue:
        response = await client.post(f"/api/conversations/{run['conversation_id']}/discussion-score")

    assert response.status_code == 202
    assert response.json() == {"celery_task_id": "celery-score-1"}
    mock_enqueue.assert_called_once_with(run["conversation_id"])

    async with async_session_factory() as session:
        task = (await session.execute(select(Task).where(Task.celery_task_id == "celery-score-1"))).scalar_one()
    assert task.conversation_id == uuid.UUID(run["conversation_id"])
    assert task.document_id is None
    assert task.collection_id is None


async def test_trigger_discussion_score_requires_ownership(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    run = await _create_run(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.post(f"/api/conversations/{run['conversation_id']}/discussion-score")

    assert response.status_code == 404


async def test_trigger_discussion_score_unknown_conversation_returns_404(client):
    response = await client.post(f"/api/conversations/{uuid.uuid4()}/discussion-score")
    assert response.status_code == 404


async def test_list_discussion_scores_empty_initially(client):
    run = await _create_run(client)
    response = await client.get(f"/api/conversations/{run['conversation_id']}/discussion-scores")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_discussion_scores_unknown_conversation_returns_404(client):
    response = await client.get(f"/api/conversations/{uuid.uuid4()}/discussion-scores")
    assert response.status_code == 404


async def test_upload_conversation_file_creates_temporary_collection(client):
    run = await _create_run(client)
    conversation_id = run["conversation_id"]

    with (
        patch("app.services.document_upload_service.storage.put_object") as mock_put,
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            return_value="celery-upload-1",
        ) as mock_enqueue,
    ):
        response = await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "notes.txt"
    assert body["type"] == "file"
    assert body["status"] == "pending"
    mock_put.assert_called_once()
    mock_enqueue.assert_called_once_with(body["id"])

    async with async_session_factory() as session:
        collection = (
            await session.execute(select(Collection).where(Collection.conversation_id == uuid.UUID(conversation_id)))
        ).scalar_one()
    assert collection.is_temporary is True
    assert collection.visibility.value == "private"


async def test_upload_conversation_file_reuses_the_same_collection_across_uploads(client):
    run = await _create_run(client)
    conversation_id = run["conversation_id"]

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            side_effect=["celery-a", "celery-b"],
        ),
    ):
        await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("a.txt", b"a", "text/plain")},
        )
        await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("b.txt", b"b", "text/plain")},
        )

    async with async_session_factory() as session:
        collections = (
            (await session.execute(select(Collection).where(Collection.conversation_id == uuid.UUID(conversation_id))))
            .scalars()
            .all()
        )
    assert len(collections) == 1


async def test_upload_conversation_file_requires_ownership(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    run = await _create_run(client)

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.post(
        f"/api/conversations/{run['conversation_id']}/documents/file",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 404


async def test_upload_to_unknown_conversation_returns_404(client):
    response = await client.post(
        f"/api/conversations/{uuid.uuid4()}/documents/file",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 404


async def test_list_conversation_documents_empty_before_any_upload(client):
    run = await _create_run(client)
    response = await client.get(f"/api/conversations/{run['conversation_id']}/documents")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_conversation_documents_after_upload(client):
    run = await _create_run(client)
    conversation_id = run["conversation_id"]

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-list-1"),
    ):
        await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    response = await client.get(f"/api/conversations/{conversation_id}/documents")
    assert response.status_code == 200
    names = [doc["name"] for doc in response.json()]
    assert names == ["notes.txt"]


async def test_list_conversation_documents_unknown_conversation_returns_404(client):
    response = await client.get(f"/api/conversations/{uuid.uuid4()}/documents")
    assert response.status_code == 404


async def test_delete_conversation_document(client):
    run = await _create_run(client)
    conversation_id = run["conversation_id"]

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-del-1"),
    ):
        upload = await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    document_id = upload.json()["id"]

    with (
        patch("app.services.document_upload_service.storage.delete_objects") as mock_delete,
        patch("app.services.document_upload_service.vector_store.delete_document_embeddings"),
    ):
        response = await client.delete(f"/api/conversations/{conversation_id}/documents/{document_id}")

    assert response.status_code == 204
    mock_delete.assert_called_once()

    listed = await client.get(f"/api/conversations/{conversation_id}/documents")
    assert listed.json() == []


async def test_delete_conversation_document_before_any_upload_returns_404(client):
    run = await _create_run(client)
    response = await client.delete(f"/api/conversations/{run['conversation_id']}/documents/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_delete_conversation_document_unknown_conversation_returns_404(client):
    response = await client.delete(f"/api/conversations/{uuid.uuid4()}/documents/{uuid.uuid4()}")
    assert response.status_code == 404
