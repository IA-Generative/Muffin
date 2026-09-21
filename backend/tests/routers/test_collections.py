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
from app.models.document import Document, DocumentPage
from app.models.feedback import (
    Feedback,
    FeedbackReason,
    FeedbackReasonCode,
    FeedbackValue,
)
from app.models.message import Message, MessageRole
from app.models.run import Run
from app.models.task import Task


@pytest.fixture
async def client():
    # A plain async httpx client, not the sync TestClient: TestClient runs each
    # request on its own short-lived event loop, and asyncpg connections from
    # the app's pooled engine can't be reused across loops - two consecutive
    # DB-backed requests in the same test blow up with "another operation is
    # in progress". Everything here shares this fixture's one event loop instead.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(Task))
        await session.execute(delete(Run))
        await session.execute(delete(Conversation))
        await session.execute(delete(Collection))
        await session.commit()


async def _create_run_with_citation(collection_id: str, grounding_valid: bool | None, query: str = "query") -> None:
    async with async_session_factory() as session:
        conversation = Conversation(user_id="dev-user", title="Test")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content=query)
        session.add(message)
        await session.flush()
        session.add(
            Run(
                user_id="dev-user",
                message_id=message.id,
                conversation_id=conversation.id,
                query=query,
                citations=[{"vdb_id": collection_id, "source": "doc-1"}],
                grounding_valid=grounding_valid,
                grounding_unsupported_claims=(["a claim"] if grounding_valid is False else None),
            )
        )
        await session.commit()


async def _create_run_with_feedback(
    collection_id: str,
    value: FeedbackValue,
    reasons: list[FeedbackReasonCode] | None = None,
    query: str = "query",
) -> None:
    async with async_session_factory() as session:
        conversation = Conversation(user_id="dev-user", title="Test")
        session.add(conversation)
        await session.flush()
        user_message = Message(conversation_id=conversation.id, role=MessageRole.USER, content=query)
        session.add(user_message)
        await session.flush()
        run = Run(
            user_id="dev-user",
            message_id=user_message.id,
            conversation_id=conversation.id,
            query=query,
            citations=[{"vdb_id": collection_id, "source": "doc-1"}],
        )
        session.add(run)
        await session.flush()
        assistant_message = Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="answer",
            run_id=run.id,
        )
        session.add(assistant_message)
        await session.flush()
        feedback = Feedback(message_id=assistant_message.id, user_id="dev-user", value=value)
        session.add(feedback)
        await session.flush()
        for reason in reasons or []:
            session.add(FeedbackReason(feedback_id=feedback.id, reason=reason))
        await session.commit()


def _as_user(user_id: str, email: str, groups: list[str] | None = None):
    def override() -> RequestContext:
        return RequestContext(
            user_id=user_id,
            email=email,
            roles=["user"],
            is_admin=False,
            groups=groups or [],
        )

    return override


async def test_create_and_list_collections(client):
    created = (await client.post("/api/collections")).json()
    assert created["name"] == "Nouvelle collection"
    assert created["embedding_model"] == "text-embedding-3-small"
    assert created["tags"] == []
    assert created["documents"] == []

    body = (await client.get("/api/collections")).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]


async def test_create_collection_accepts_a_prefilled_name_and_description(client):
    response = await client.post(
        "/api/collections", json={"name": "Rapports financiers", "description": "Rapports trimestriels."}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Rapports financiers"
    assert body["description"] == "Rapports trimestriels."


async def test_list_collections_excludes_temporary_collections(client):
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        run = (await client.post("/api/runs", json={"query": "hi"})).json()

    with (
        patch("app.services.document_upload_service.storage.put_object"),
        patch("app.services.document_upload_service.enqueue_process_document", return_value="celery-upload-1"),
    ):
        await client.post(
            f"/api/conversations/{run['conversation_id']}/documents/file",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )

    async with async_session_factory() as session:
        temp_collection = (
            await session.execute(
                select(Collection).where(Collection.conversation_id == uuid.UUID(run["conversation_id"]))
            )
        ).scalar_one()
    assert temp_collection.is_temporary is True

    body = (await client.get("/api/collections")).json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_get_collection_not_found_returns_404(client):
    response = await client.get("/api/collections/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_update_collection_name_description_and_tags(client):
    created = (await client.post("/api/collections")).json()

    response = await client.patch(
        f"/api/collections/{created['id']}",
        json={
            "name": "Projets",
            "description": "Notes de projet",
            "tags": ["a", "b", "a"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Projets"
    assert body["description"] == "Notes de projet"
    assert body["tags"] == ["a", "b"]
    assert body["description_meta"]["updated_by"] == "dev@example.com"
    assert body["tags_meta"]["updated_by"] == "dev@example.com"


async def test_update_settings_persists_chunking_instructions_and_models(client):
    created = (await client.post("/api/collections")).json()

    response = await client.patch(
        f"/api/collections/{created['id']}/settings",
        json={
            "chunking_strategy": "fixed",
            "chunk_size": 800,
            "chunk_overlap": 100,
            "instructions": {
                "qa": "Sois concis",
                "extraction": "",
                "chunking": "",
                "tagging": "",
                "summary": "",
            },
            "generation_models": {"qa": "gpt-4o-mini"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["chunking_settings"] == {
        "strategy": "fixed",
        "chunk_size": 800,
        "chunk_overlap": 100,
    }
    assert body["instructions"]["qa"] == "Sois concis"
    assert body["generation_models"]["qa"] == "gpt-4o-mini"
    assert body["generation_models"]["tagging"] is None
    # Untouched by this request.
    assert body["reindex_required"] is False


async def test_update_settings_changing_embedding_model_requires_reindex(client):
    created = (await client.post("/api/collections")).json()
    assert created["embedding_model"] == "text-embedding-3-small"

    response = await client.patch(
        f"/api/collections/{created['id']}/settings",
        json={"embedding_model": "text-embedding-3-large"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["embedding_model"] == "text-embedding-3-large"
    assert body["reindex_required"] is True


async def test_update_settings_generation_models_merge_not_replace(client):
    created = (await client.post("/api/collections")).json()
    await client.patch(
        f"/api/collections/{created['id']}/settings",
        json={"generation_models": {"qa": "model-a"}},
    )

    response = await client.patch(
        f"/api/collections/{created['id']}/settings",
        json={"generation_models": {"tagging": "model-b"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generation_models"]["qa"] == "model-a"
    assert body["generation_models"]["tagging"] == "model-b"


async def test_pipeline_windows_default_when_never_saved(client):
    created = (await client.post("/api/collections")).json()

    assert created["pipeline_windows"] == {
        "summary_pages_per_map": 5,
        "qa_window_pages": 2,
        "qa_slide_pages": 1,
        "qa_questions_per_window": 3,
        "extraction_window_pages": 4,
        "extraction_slide_pages": 1,
        "chunking_window_pages": 2,
        "chunking_slide_pages": 1,
        "collection_qa_count": 3,
    }


async def test_update_settings_pipeline_windows_merge_not_replace(client):
    created = (await client.post("/api/collections")).json()

    await client.patch(
        f"/api/collections/{created['id']}/settings",
        json={"pipeline_windows": {"qa_window_pages": 3, "qa_slide_pages": 2}},
    )
    response = await client.patch(
        f"/api/collections/{created['id']}/settings",
        json={"pipeline_windows": {"summary_pages_per_map": 8}},
    )

    assert response.status_code == 200
    body = response.json()["pipeline_windows"]
    assert body["qa_window_pages"] == 3
    assert body["qa_slide_pages"] == 2
    assert body["summary_pages_per_map"] == 8
    # Untouched keys keep their defaults.
    assert body["extraction_window_pages"] == 4


async def test_update_settings_for_unknown_collection_returns_404(client):
    response = await client.patch(
        f"/api/collections/{uuid.uuid4()}/settings",
        json={"embedding_model": "text-embedding-3-large"},
    )
    assert response.status_code == 404


async def test_delete_collection(client):
    created = (await client.post("/api/collections")).json()

    response = await client.delete(f"/api/collections/{created['id']}")
    assert response.status_code == 204


async def test_delete_collection_removes_rustfs_objects(client):
    created = (await client.post("/api/collections")).json()

    async with async_session_factory() as session:
        document = Document(
            collection_id=created["id"],
            name="report.pdf",
            type="file",
            storage_key="docs/report.pdf",
        )
        session.add(document)
        await session.flush()
        session.add(
            DocumentPage(
                document_id=document.id,
                page_number=1,
                content="hi",
                screenshot="screens/p1.png",
            )
        )
        await session.commit()

    with patch("app.services.collection_service.storage.delete_objects") as mock_delete:
        response = await client.delete(f"/api/collections/{created['id']}")

    assert response.status_code == 204
    mock_delete.assert_called_once()
    (deleted_keys,), _ = mock_delete.call_args
    assert set(deleted_keys) == {"docs/report.pdf", "screens/p1.png"}

    assert (await client.get(f"/api/collections/{created['id']}")).status_code == 404


async def test_pagination(client):
    for _ in range(3):
        await client.post("/api/collections")

    first_page = (await client.get("/api/collections", params={"page": 1, "page_size": 2})).json()
    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2

    second_page = (await client.get("/api/collections", params={"page": 2, "page_size": 2})).json()
    assert len(second_page["items"]) == 1


async def test_collections_are_scoped_to_their_owner(client):
    app.dependency_overrides[get_current_user] = _as_user("user-a", "a@example.com")
    created = (await client.post("/api/collections")).json()

    app.dependency_overrides[get_current_user] = _as_user("user-b", "b@example.com")
    try:
        assert (await client.get("/api/collections")).json()["total"] == 0
        assert (await client.get(f"/api/collections/{created['id']}")).status_code == 404
    finally:
        del app.dependency_overrides[get_current_user]


async def test_list_qa_pairs_includes_document_name_as_source(client):
    from app.models.qa import QaOrigin, QaPair

    collection_id = (await client.post("/api/collections")).json()["id"]
    async with async_session_factory() as session:
        document = Document(collection_id=collection_id, name="report.pdf", type="url")
        session.add(document)
        await session.flush()
        session.add(
            QaPair(
                collection_id=collection_id,
                document_id=document.id,
                question="What is this?",
                answer="A report.",
                origin=QaOrigin.GENERATED,
                validated=False,
            )
        )
        await session.commit()

    response = await client.get(f"/api/collections/{collection_id}/qa-pairs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["question"] == "What is this?"
    assert body[0]["source"] == "report.pdf"
    assert body[0]["origin"] == "generated"


async def test_list_qa_pairs_for_unknown_collection_returns_404(client):
    response = await client.get(f"/api/collections/{uuid.uuid4()}/qa-pairs")
    assert response.status_code == 404


async def test_list_qa_pairs_filtered_by_document(client):
    from app.models.qa import QaOrigin, QaPair

    collection_id = (await client.post("/api/collections")).json()["id"]
    async with async_session_factory() as session:
        report = Document(collection_id=collection_id, name="report.pdf", type="url")
        memo = Document(collection_id=collection_id, name="memo.pdf", type="url")
        session.add_all([report, memo])
        await session.flush()
        session.add_all(
            [
                QaPair(
                    collection_id=collection_id,
                    document_id=report.id,
                    question="Report question",
                    answer="Report answer",
                    origin=QaOrigin.GENERATED,
                    validated=False,
                ),
                QaPair(
                    collection_id=collection_id,
                    document_id=memo.id,
                    question="Memo question",
                    answer="Memo answer",
                    origin=QaOrigin.GENERATED,
                    validated=False,
                ),
            ]
        )
        await session.commit()
        report_id = report.id

    response = await client.get(
        f"/api/collections/{collection_id}/qa-pairs",
        params={"document_id": str(report_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["question"] == "Report question"


async def test_groundedness_stats_aggregates_by_collection(client):
    collection_id = (await client.post("/api/collections")).json()["id"]
    other_collection_id = (await client.post("/api/collections")).json()["id"]

    await _create_run_with_citation(collection_id, grounding_valid=True, query="grounded")
    await _create_run_with_citation(collection_id, grounding_valid=False, query="ungrounded")
    # Not evaluated yet (e.g. validate_grounding was skipped - see agent_service.py) - shouldn't
    # count as either grounded or ungrounded.
    await _create_run_with_citation(collection_id, grounding_valid=None, query="unevaluated")
    # A different collection's ungrounded run must never leak into this one's stats.
    await _create_run_with_citation(other_collection_id, grounding_valid=False, query="elsewhere")

    response = await client.get(f"/api/collections/{collection_id}/groundedness")

    assert response.status_code == 200
    body = response.json()
    assert body["evaluated_count"] == 2
    assert body["ungrounded_count"] == 1
    assert len(body["recent_ungrounded"]) == 1
    assert body["recent_ungrounded"][0]["query"] == "ungrounded"
    assert body["recent_ungrounded"][0]["unsupported_claims"] == ["a claim"]


async def test_groundedness_stats_for_unknown_collection_returns_404(client):
    response = await client.get(f"/api/collections/{uuid.uuid4()}/groundedness")
    assert response.status_code == 404


async def test_trigger_evaluation_enqueues_and_returns_celery_task_id(client):
    collection_id = (await client.post("/api/collections")).json()["id"]

    with patch(
        "app.services.evaluation_service.enqueue_run_evaluation",
        return_value="celery-eval-1",
    ) as mock_enqueue:
        response = await client.post(f"/api/collections/{collection_id}/evaluations", json={"k": 8})

    assert response.status_code == 202
    assert response.json() == {"celery_task_id": "celery-eval-1"}
    mock_enqueue.assert_called_once_with(collection_id, 8, False)

    # The Task row (progress/logs tracking) is created directly here, not by a worker round-trip
    # - see EvaluationService.trigger's docstring.
    async with async_session_factory() as session:
        task = (await session.execute(select(Task).where(Task.celery_task_id == "celery-eval-1"))).scalar_one()
    assert task.owner_id == "dev-user"
    assert task.collection_id == uuid.UUID(collection_id)
    assert task.document_id is None
    assert task.task_name == "app.tasks.run_evaluation"


async def test_trigger_evaluation_defaults_k(client):
    collection_id = (await client.post("/api/collections")).json()["id"]

    with patch(
        "app.services.evaluation_service.enqueue_run_evaluation",
        return_value="celery-eval-2",
    ) as mock_enqueue:
        response = await client.post(f"/api/collections/{collection_id}/evaluations", json={})

    assert response.status_code == 202
    mock_enqueue.assert_called_once_with(collection_id, 5, False)


async def test_trigger_evaluation_for_unknown_collection_returns_404(client):
    response = await client.post(f"/api/collections/{uuid.uuid4()}/evaluations", json={})
    assert response.status_code == 404


async def test_list_evaluations_empty_initially(client):
    collection_id = (await client.post("/api/collections")).json()["id"]
    response = await client.get(f"/api/collections/{collection_id}/evaluations")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_evaluations_for_unknown_collection_returns_404(client):
    response = await client.get(f"/api/collections/{uuid.uuid4()}/evaluations")
    assert response.status_code == 404


async def test_feedback_stats_aggregates_by_collection(client):
    collection_id = (await client.post("/api/collections")).json()["id"]
    other_collection_id = (await client.post("/api/collections")).json()["id"]

    await _create_run_with_feedback(collection_id, FeedbackValue.UP, query="good")
    await _create_run_with_feedback(
        collection_id,
        FeedbackValue.DOWN,
        reasons=[FeedbackReasonCode.INCORRECT_ANSWER, FeedbackReasonCode.NOT_USEFUL],
        query="bad",
    )
    # A different collection's feedback must never leak into this one's stats.
    await _create_run_with_feedback(other_collection_id, FeedbackValue.DOWN, query="elsewhere")

    response = await client.get(f"/api/collections/{collection_id}/feedback")

    assert response.status_code == 200
    body = response.json()
    assert body["up_count"] == 1
    assert body["down_count"] == 1
    assert body["reason_counts"] == {"incorrect_answer": 1, "not_useful": 1}


async def test_feedback_stats_for_unknown_collection_returns_404(client):
    response = await client.get(f"/api/collections/{uuid.uuid4()}/feedback")
    assert response.status_code == 404


async def test_list_entities(client):
    from app.models.entity import Entity, EntityType

    collection_id = (await client.post("/api/collections")).json()["id"]
    async with async_session_factory() as session:
        session.add(
            Entity(
                collection_id=collection_id,
                name="Acme Corp",
                type=EntityType.ORGANISATION,
                mentions=3,
            )
        )
        await session.commit()

    response = await client.get(f"/api/collections/{collection_id}/entities")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "Acme Corp"
    assert body[0]["type"] == "organisation"
    assert body[0]["mentions"] == 3


async def test_list_relations_uses_entity_names_for_from_and_to(client):
    from app.models.entity import Entity, EntityType, Relation

    collection_id = (await client.post("/api/collections")).json()["id"]
    async with async_session_factory() as session:
        alice = Entity(
            collection_id=collection_id,
            name="Alice",
            type=EntityType.PERSONNE,
            mentions=1,
        )
        acme = Entity(
            collection_id=collection_id,
            name="Acme Corp",
            type=EntityType.ORGANISATION,
            mentions=1,
        )
        session.add_all([alice, acme])
        await session.flush()
        session.add(
            Relation(
                collection_id=collection_id,
                from_entity_id=alice.id,
                to_entity_id=acme.id,
                type="works_at",
            )
        )
        await session.commit()

    response = await client.get(f"/api/collections/{collection_id}/relations")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["from"] == "Alice"
    assert body[0]["to"] == "Acme Corp"
    assert body[0]["type"] == "works_at"
