import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.task import Task

USER_ID = "dev-user"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Document))
        await session.execute(delete(Collection))
        await session.execute(delete(Conversation))
        await session.commit()


def _as_user(user_id: str, email: str):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False)

    return override


async def _create_conversation_file(client, *, celery_task_id: str = "celery-upload-1") -> tuple[uuid.UUID, uuid.UUID]:
    """Uploads a file straight into a brand-new conversation (§ conv-files) - returns
    (conversation_id, document_id)."""
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value=celery_task_id),
        patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"),
    ):
        run = await client.post("/api/runs", json={"query": "hi"})
        conversation_id = run.json()["conversation_id"]
        upload = await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    return uuid.UUID(conversation_id), uuid.UUID(upload.json()["id"])


async def test_list_files_to_file_empty_initially(client):
    response = await client.get("/api/filing/documents")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_files_to_file_includes_a_conversation_file(client):
    _, document_id = await _create_conversation_file(client)

    response = await client.get("/api/filing/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(document_id)
    assert body[0]["collection_is_temporary"] is True
    assert body[0]["collection_editable"] is True
    assert body[0]["filing_dismissed"] is False


async def test_list_files_to_file_only_shows_the_current_user_s_own_uploads(client):
    await _create_conversation_file(client)

    app.dependency_overrides[get_current_user] = _as_user("someone-else", "someone-else@example.com")
    response = await client.get("/api/filing/documents")

    assert response.status_code == 200
    assert response.json() == []


async def test_decide_filing_dismiss_sets_the_flag_without_moving(client):
    _, document_id = await _create_conversation_file(client)

    response = await client.post(f"/api/filing/documents/{document_id}/decision", json={"action": "dismiss"})

    assert response.status_code == 200
    assert response.json()["filing_dismissed"] is True
    async with async_session_factory() as session:
        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
    assert document.filing_dismissed is True
    original_collection_id = document.collection_id

    # A dismissed file is still un-filed - it keeps showing up on the review page.
    listed = await client.get("/api/filing/documents")
    assert len(listed.json()) == 1
    assert document.collection_id == original_collection_id


async def test_decide_filing_accept_moves_the_document_to_the_suggested_collection(client, monkeypatch):
    _, document_id = await _create_conversation_file(client)
    async with async_session_factory() as session:
        target = Collection(owner_id=USER_ID, name="Rapports", description="Rapports trimestriels.")
        from app.models.collection import CollectionSettings

        target.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(target)
        await session.flush()
        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
        document.suggested_collection_id = target.id
        document.suggested_collection_score = 0.9
        await session.commit()
        target_id = target.id

    with (
        patch("app.services.document_upload_service.vector_store.delete_document_embeddings"),
        patch(
            "app.services.document_upload_service.enqueue_process_document", return_value="celery-refile-1"
        ) as mock_enqueue,
    ):
        response = await client.post(f"/api/filing/documents/{document_id}/decision", json={"action": "accept"})

    assert response.status_code == 200
    mock_enqueue.assert_called_once()
    async with async_session_factory() as session:
        document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
    assert document.collection_id == target_id
    assert document.status == "pending"
    assert document.summary is None

    # Moved out of its temporary collection - no longer on the review page.
    listed = await client.get("/api/filing/documents")
    assert listed.json() == []


async def test_decide_filing_choose_other_requires_owning_the_target_collection(client):
    _, document_id = await _create_conversation_file(client)
    async with async_session_factory() as session:
        from app.models.collection import CollectionSettings

        not_mine = Collection(owner_id="someone-else", name="Not mine", description="")
        not_mine.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(not_mine)
        await session.commit()
        not_mine_id = not_mine.id

    response = await client.post(
        f"/api/filing/documents/{document_id}/decision",
        json={"action": "choose_other", "target_collection_id": str(not_mine_id)},
    )

    assert response.status_code == 404


async def test_decide_filing_accept_without_a_suggestion_is_a_bad_request(client):
    _, document_id = await _create_conversation_file(client)

    response = await client.post(f"/api/filing/documents/{document_id}/decision", json={"action": "accept"})

    assert response.status_code == 400


async def test_decide_filing_by_someone_who_did_not_upload_it_returns_404(client):
    _, document_id = await _create_conversation_file(client)

    app.dependency_overrides[get_current_user] = _as_user("someone-else", "someone-else@example.com")
    response = await client.post(f"/api/filing/documents/{document_id}/decision", json={"action": "dismiss"})

    assert response.status_code == 404


async def test_upload_standalone_document_lands_in_a_personal_holding_collection(client):
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-standalone-1"),
    ):
        response = await client.post(
            "/api/filing/documents/upload", files={"file": ("standalone.txt", b"hello", "text/plain")}
        )

    assert response.status_code == 201
    document_id = uuid.UUID(response.json()["id"])

    listed = await client.get("/api/filing/documents")
    body = listed.json()
    assert len(body) == 1
    assert body[0]["id"] == str(document_id)
    assert body[0]["collection_is_temporary"] is True
    assert body[0]["collection_name"] == "Fichiers à ranger"


async def test_upload_standalone_document_reuses_the_same_holding_collection(client):
    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch(
            "app.services.document_upload_service.enqueue_process_document",
            side_effect=["celery-standalone-1", "celery-standalone-2"],
        ),
    ):
        first = await client.post("/api/filing/documents/upload", files={"file": ("a.txt", b"hello", "text/plain")})
        second = await client.post("/api/filing/documents/upload", files={"file": ("b.txt", b"world", "text/plain")})

    assert first.status_code == 201
    assert second.status_code == 201

    async with async_session_factory() as session:
        from app.models.document import Document as DocumentModel

        documents = (
            (await session.execute(select(DocumentModel).where(DocumentModel.added_by_user_id == USER_ID)))
            .scalars()
            .all()
        )
    collection_ids = {document.collection_id for document in documents}
    assert len(collection_ids) == 1  # both uploads reused the same holding collection
