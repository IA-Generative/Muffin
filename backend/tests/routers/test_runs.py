import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.conversation import Conversation
from app.models.run import Run
from app.models.task import Task


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        # Conversation cascades to Task (via Document) and to a temporary Collection
        # (both DB-level ondelete=CASCADE) - Task is still deleted explicitly first since
        # a bulk DELETE doesn't itself depend on that, and it's the row whose
        # ix_tasks_celery_task_id unique index bites hardest if ever left behind.
        await session.execute(delete(Task))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.commit()


def _as_user(user_id: str, email: str, groups: list[str] | None = None):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=email, roles=["user"], is_admin=False, groups=groups or [])

    return override


async def _create_run(client, query: str = "What is the telework policy?"):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        response = await client.post("/api/runs", json={"query": query})
    return response


async def test_create_run_creates_conversation_message_and_run(client):
    response = await _create_run(client)

    assert response.status_code == 202
    body = response.json()
    assert body["query"] == "What is the telework policy?"
    assert body["status"] == "queued"
    assert body["cancel_requested"] is False
    assert body["answer"] is None

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(body["id"]))
    assert run is not None
    assert run.celery_task_id == "celery-run-1"
    assert run.message_id is not None
    assert run.conversation_id is not None


async def test_create_run_persists_pinned_collection_ids(client):
    collection_id = uuid.uuid4()
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        response = await client.post(
            "/api/runs", json={"query": "What is this?", "collection_ids": [str(collection_id)]}
        )
    assert response.status_code == 202

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(response.json()["id"]))
    assert run.pinned_collection_ids == [str(collection_id)]


async def test_create_run_snapshots_the_requesting_user_s_groups(client):
    app.dependency_overrides[get_current_user] = _as_user("owner", "owner@example.com", groups=["/hr-team"])
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        response = await client.post("/api/runs", json={"query": "What is this?"})
    assert response.status_code == 202

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(response.json()["id"]))
    assert run.user_groups == ["/hr-team"]


async def test_create_run_web_search_enabled_defaults_to_false(client):
    response = await _create_run(client)
    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(response.json()["id"]))
    assert run.web_search_enabled is False


async def test_create_run_persists_web_search_enabled_when_requested(client):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        response = await client.post("/api/runs", json={"query": "What's the weather?", "web_search_enabled": True})
    assert response.status_code == 202

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(response.json()["id"]))
    assert run.web_search_enabled is True


async def test_create_run_without_pinned_collections_stores_none(client):
    response = await _create_run(client)

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(response.json()["id"]))
    assert run.pinned_collection_ids is None


async def test_create_run_reuses_an_existing_conversation(client):
    first = (await _create_run(client)).json()
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-2"):
        second = await client.post(
            "/api/runs", json={"query": "And what about leave policy?", "conversation_id": first["conversation_id"]}
        )

    assert second.status_code == 202
    assert second.json()["conversation_id"] == first["conversation_id"]
    # But each run still gets its own message.
    assert second.json()["id"] != first["id"]


async def test_create_run_for_unknown_conversation_returns_404(client):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-3"):
        response = await client.post("/api/runs", json={"query": "hello", "conversation_id": str(uuid.uuid4())})
    assert response.status_code == 404


async def test_get_run_not_found(client):
    response = await client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_runs_are_scoped_to_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    created = (await _create_run(client)).json()

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.get(f"/api/runs/{created['id']}")
    assert response.status_code == 404


async def test_list_run_events_empty_initially(client):
    created = (await _create_run(client)).json()
    response = await client.get(f"/api/runs/{created['id']}/events")
    assert response.status_code == 200
    assert response.json() == []


async def test_cancel_run_sets_cancel_requested_and_revokes(client):
    created = (await _create_run(client)).json()

    with patch("app.services.run_service.revoke_task") as mock_revoke:
        response = await client.post(f"/api/runs/{created['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["cancel_requested"] is True
    mock_revoke.assert_called_once_with("celery-run-1")


async def test_cancel_unknown_run_returns_404(client):
    response = await client.post(f"/api/runs/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


async def test_resume_run_waiting_for_user_dispatches_and_returns_ok(client):
    from app.models.run import RunStatus

    created = (await _create_run(client)).json()
    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(created["id"]))
        run.status = RunStatus.WAITING_FOR_USER
        run.pending_human_action = {"question": "Which department do you mean?"}
        await session.commit()

    with patch("app.services.run_service.enqueue_resume_agent", return_value="celery-resume-1") as mock_enqueue:
        response = await client.post(f"/api/runs/{created['id']}/resume", json={"answer": "HR"})

    assert response.status_code == 200
    mock_enqueue.assert_called_once_with(created["id"], "HR")

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(created["id"]))
    assert run.celery_task_id == "celery-resume-1"


async def test_resume_run_not_waiting_returns_409(client):
    created = (await _create_run(client)).json()  # still "queued", never entered waiting_for_user

    response = await client.post(f"/api/runs/{created['id']}/resume", json={"answer": "HR"})

    assert response.status_code == 409


async def test_resume_unknown_run_returns_404(client):
    response = await client.post(f"/api/runs/{uuid.uuid4()}/resume", json={"answer": "HR"})
    assert response.status_code == 404


async def _add_assistant_message(run_id: str, content: str = "The answer.") -> uuid.UUID:
    from app.models.message import Message, MessageRole
    from app.models.run import Run

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(run_id))
        message = Message(
            conversation_id=run.conversation_id, role=MessageRole.ASSISTANT, content=content, run_id=run.id
        )
        session.add(message)
        await session.commit()
        return message.id


async def _link_source(message_id: uuid.UUID, title: str = "policy.pdf", url: str | None = None) -> uuid.UUID:
    from app.models.source import MessageSource, Source

    async with async_session_factory() as session:
        source = Source(title=title, url=url)
        session.add(source)
        await session.flush()
        session.add(MessageSource(message_id=message_id, source_id=source.id))
        await session.commit()
        return source.id


async def test_submit_feedback_persists_value_reasons_and_comment(client):
    created = (await _create_run(client)).json()
    await _add_assistant_message(created["id"])

    response = await client.post(
        f"/api/runs/{created['id']}/feedback",
        json={"value": "down", "reasons": ["incorrect_answer", "not_useful"], "comment": "Wrong date."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["value"] == "down"
    assert sorted(body["reasons"]) == ["incorrect_answer", "not_useful"]
    assert body["comment"] == "Wrong date."


async def test_submit_feedback_up_needs_no_reasons(client):
    created = (await _create_run(client)).json()
    await _add_assistant_message(created["id"])

    response = await client.post(f"/api/runs/{created['id']}/feedback", json={"value": "up"})

    assert response.status_code == 201
    assert response.json()["reasons"] == []


async def test_submit_feedback_on_unknown_run_returns_404(client):
    response = await client.post(f"/api/runs/{uuid.uuid4()}/feedback", json={"value": "up"})
    assert response.status_code == 404


async def test_submit_feedback_on_a_run_without_an_answer_yet_returns_409(client):
    created = (await _create_run(client)).json()
    response = await client.post(f"/api/runs/{created['id']}/feedback", json={"value": "up"})
    assert response.status_code == 409


async def test_submit_feedback_is_scoped_to_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    created = (await _create_run(client)).json()
    await _add_assistant_message(created["id"])

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    response = await client.post(f"/api/runs/{created['id']}/feedback", json={"value": "up"})
    assert response.status_code == 404


async def test_submit_feedback_validates_a_source_actually_cited_on_the_message(client):
    from app.models.feedback import FeedbackSource, FeedbackSourceRole

    created = (await _create_run(client)).json()
    message_id = await _add_assistant_message(created["id"])
    source_id = await _link_source(message_id)

    response = await client.post(
        f"/api/runs/{created['id']}/feedback", json={"value": "down", "validated_source_ids": [str(source_id)]}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["validated_source_ids"] == [str(source_id)]

    async with async_session_factory() as session:
        rows = (await session.execute(select(FeedbackSource))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_id == source_id
    assert rows[0].role == FeedbackSourceRole.VALIDATED


async def test_submit_feedback_drops_a_source_id_not_cited_on_the_message(client):
    """A validated_source_ids the client supplies is never trusted at face value - only what's
    actually linked to this message via message_sources gets attached (see
    SourceRepository.filter_linked)."""
    created = (await _create_run(client)).json()
    await _add_assistant_message(created["id"])
    # A real Source, but never linked to *this* message - e.g. cited on a different run.
    unrelated_source_id = uuid.uuid4()
    async with async_session_factory() as session:
        from app.models.source import Source

        session.add(Source(id=unrelated_source_id, title="Elsewhere", url="https://example.com"))
        await session.commit()

    response = await client.post(
        f"/api/runs/{created['id']}/feedback",
        json={"value": "down", "validated_source_ids": [str(unrelated_source_id)]},
    )

    assert response.status_code == 201
    assert response.json()["validated_source_ids"] == []

    async with async_session_factory() as session:
        from app.models.feedback import FeedbackSource

        rows = (await session.execute(select(FeedbackSource))).scalars().all()
    assert rows == []


async def test_submit_feedback_creates_a_source_for_an_added_url(client):
    from app.models.feedback import FeedbackSource, FeedbackSourceRole
    from app.models.source import Source

    created = (await _create_run(client)).json()
    await _add_assistant_message(created["id"])

    response = await client.post(
        f"/api/runs/{created['id']}/feedback",
        json={
            "value": "down",
            "added_sources": [{"title": "Better source", "url": "https://example.com/better"}],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["added_source_ids"]) == 1

    async with async_session_factory() as session:
        source = await session.get(Source, uuid.UUID(body["added_source_ids"][0]))
        assert source.title == "Better source"
        assert source.url == "https://example.com/better"
        rows = (await session.execute(select(FeedbackSource))).scalars().all()
    assert len(rows) == 1
    assert rows[0].role == FeedbackSourceRole.ADDED


async def test_run_out_exposes_pending_human_action(client):
    from app.models.run import RunStatus

    created = (await _create_run(client)).json()
    assert created["pending_human_action"] is None

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(created["id"]))
        run.status = RunStatus.WAITING_FOR_USER
        run.pending_human_action = {"question": "Which department do you mean?"}
        await session.commit()

    response = await client.get(f"/api/runs/{created['id']}")
    assert response.json()["pending_human_action"] == {"question": "Which department do you mean?"}


async def test_create_run_auto_pins_the_conversation_s_temporary_collection(client):
    first = await _create_run(client)
    conversation_id = first.json()["conversation_id"]

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-upload-1"),
    ):
        await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    async with async_session_factory() as session:
        from app.models.collection import Collection

        temp_collection = (
            await session.execute(select(Collection).where(Collection.conversation_id == uuid.UUID(conversation_id)))
        ).scalar_one()

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-2"):
        second = await client.post(
            "/api/runs", json={"query": "What does the file say?", "conversation_id": conversation_id}
        )
    assert second.status_code == 202

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(second.json()["id"]))
    assert run.pinned_collection_ids == [str(temp_collection.id)]


async def test_create_run_does_not_duplicate_an_already_pinned_temporary_collection(client):
    first = await _create_run(client)
    conversation_id = first.json()["conversation_id"]

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-upload-1"),
    ):
        await client.post(
            f"/api/conversations/{conversation_id}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    async with async_session_factory() as session:
        from app.models.collection import Collection

        temp_collection = (
            await session.execute(select(Collection).where(Collection.conversation_id == uuid.UUID(conversation_id)))
        ).scalar_one()

    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-2"):
        second = await client.post(
            "/api/runs",
            json={
                "query": "What does the file say?",
                "conversation_id": conversation_id,
                "collection_ids": [str(temp_collection.id)],
            },
        )

    async with async_session_factory() as session:
        run = await session.get(Run, uuid.UUID(second.json()["id"]))
    assert run.pinned_collection_ids == [str(temp_collection.id)]
