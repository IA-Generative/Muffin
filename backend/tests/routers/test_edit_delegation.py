import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import RequestContext, get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings, CollectionVisibility
from app.models.conversation import Conversation
from app.models.document import Document, DocumentKind, DocumentStatus, DocumentType
from app.models.document_revision import DocumentRevision, RevisionOrigin
from app.models.message import Message, MessageRole
from app.models.run import Run
from app.models.source import Source
from app.models.task import Task

DRAFTS = "app.services.document_draft_service"
API_KEY = "test-worker-key"
WORKER = {"X-API-Key": API_KEY}
ODT = "application/vnd.oasis.opendocument.text"


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


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
        # Sources aren't owned by a run or a collection: a citation test leaves them behind, and
        # test_internal_runs counts every Source row in the table.
        await session.execute(delete(Source))
        await session.commit()


class Queue:
    def __init__(self) -> None:
        self.jobs: list[tuple[dict, str]] = []

    def enqueue(self, payload, task_id=None):
        self.jobs.append((payload, task_id))
        return task_id


@pytest.fixture
def queue():
    state = Queue()
    with (
        patch(f"{DRAFTS}.enqueue_edit_document", state.enqueue),
        patch(f"{DRAFTS}.storage.delete_objects"),
    ):
        yield state


async def _seed_document(
    owner_id: str,
    *,
    name: str = "procedure.odt",
    kind: DocumentKind = DocumentKind.LIVING,
    visibility: CollectionVisibility = CollectionVisibility.PRIVATE,
    temporary: bool = False,
    summary: str | None = "Les étapes d'arrivée d'un agent.",
) -> tuple[uuid.UUID, uuid.UUID]:
    """A collection with one document - living ones get a first revision, like a real upload."""
    async with async_session_factory() as session:
        collection = Collection(
            owner_id=owner_id, name=f"Collection de {owner_id}", description="", visibility=visibility,
            is_temporary=temporary,
        )  # fmt: skip
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(
            collection_id=collection.id,
            name=name,
            type=DocumentType.FILE,
            kind=kind,
            storage_key=f"documents/{collection.id}/x-{name}",
            status=DocumentStatus.INDEXED,
            summary=summary,
        )
        session.add(document)
        await session.flush()
        if kind == DocumentKind.LIVING:
            session.add(
                DocumentRevision(
                    document_id=document.id,
                    number=1,
                    storage_key=document.storage_key,
                    filename=name,
                    format="odt",
                    origin=RevisionOrigin.UPLOAD,
                )
            )
        await session.commit()
        return collection.id, document.id


async def _seed_run(user_id="dev-user", *, groups=None, is_admin=False, display="Jean D.") -> uuid.UUID:
    async with async_session_factory() as session:
        conversation = Conversation(user_id=user_id, title="Test")
        session.add(conversation)
        await session.flush()
        message = Message(conversation_id=conversation.id, role=MessageRole.USER, content="Ajoute un numéro")
        session.add(message)
        await session.flush()
        run = Run(
            user_id=user_id,
            message_id=message.id,
            conversation_id=conversation.id,
            query="Ajoute un numéro",
            user_groups=groups,
            user_is_admin=is_admin,
            user_display=display,
        )
        session.add(run)
        await session.commit()
        return run.id


def _as_user(user_id: str, *, is_admin: bool = False):
    def override() -> RequestContext:
        return RequestContext(user_id=user_id, email=f"{user_id}@example.org", roles=["user"], is_admin=is_admin)

    return override


# -- who may edit a living document -------------------------------------------------------------


async def test_the_owner_an_admin_on_a_visible_collection_and_nobody_else_may_edit(client, queue):
    collection_id, document_id = await _seed_document("owner", visibility=CollectionVisibility.PUBLIC)
    url = f"/api/collections/{collection_id}/documents/{document_id}/revisions"

    app.dependency_overrides[get_current_user] = _as_user("owner")
    assert (await client.get(url)).status_code == 200

    app.dependency_overrides[get_current_user] = _as_user("stranger")
    assert (await client.get(url)).status_code == 403  # can see it (public), may not edit it

    app.dependency_overrides[get_current_user] = _as_user("admin-user", is_admin=True)
    assert (await client.get(url)).status_code == 200


async def test_an_admin_cannot_edit_someone_elses_private_collection(client, queue):
    collection_id, document_id = await _seed_document("owner", visibility=CollectionVisibility.PRIVATE)
    app.dependency_overrides[get_current_user] = _as_user("admin-user", is_admin=True)

    response = await client.get(f"/api/collections/{collection_id}/documents/{document_id}/revisions")

    assert response.status_code == 404  # not even visible to them: its existence isn't theirs to learn


async def test_a_visible_collection_that_is_not_editable_says_so_for_drafts_too(client, queue):
    collection_id, document_id = await _seed_document("owner", visibility=CollectionVisibility.PUBLIC)
    app.dependency_overrides[get_current_user] = _as_user("stranger")

    response = await client.post(
        f"/api/collections/{collection_id}/documents/{document_id}/draft", json={"prompt": "Ajoute un numéro"}
    )

    assert response.status_code == 403
    assert queue.jobs == []


async def test_an_admin_can_start_a_draft_on_a_public_collection_they_do_not_own(client, queue):
    collection_id, document_id = await _seed_document("owner", visibility=CollectionVisibility.PUBLIC)
    app.dependency_overrides[get_current_user] = _as_user("admin-user", is_admin=True)

    response = await client.post(
        f"/api/collections/{collection_id}/documents/{document_id}/draft", json={"prompt": "Ajoute un numéro"}
    )

    assert response.status_code == 202
    assert len(queue.jobs) == 1


# -- the run remembers who asked ----------------------------------------------------------------


async def test_a_run_snapshots_whether_the_user_is_an_admin_and_how_to_show_them(client):
    app.dependency_overrides[get_current_user] = lambda: RequestContext(
        user_id="admin-user",
        email="a@example.org",
        roles=["admin"],
        is_admin=True,
        first_name="Marie",
        last_name="Lefèvre",
    )
    with patch("app.services.run_service.enqueue_run_agent", return_value="celery-run-1"):
        created = await client.post("/api/runs", json={"query": "Ajoute un numéro"})

    async with async_session_factory() as session:
        run = await session.scalar(select(Run).where(Run.id == uuid.UUID(created.json()["id"])))
    assert (run.user_is_admin, run.user_display) == (True, "Marie L.")


# -- what the research agent can do through the backend -----------------------------------------


async def test_the_agent_is_offered_only_the_living_documents_its_user_may_edit(client, queue):
    await _seed_document("dev-user", name="mine.odt")
    await _seed_document("dev-user", name="standard.pdf", kind=DocumentKind.STANDARD)
    await _seed_document("dev-user", name="temp.odt", temporary=True)
    await _seed_document("someone", name="public.odt", visibility=CollectionVisibility.PUBLIC)
    await _seed_document("someone", name="private.odt")
    run_id = await _seed_run("dev-user")
    admin_run_id = await _seed_run("dev-user", is_admin=True)

    mine = (await client.get(f"/api/internal/runs/{run_id}/editable-documents", headers=WORKER)).json()
    admin = (await client.get(f"/api/internal/runs/{admin_run_id}/editable-documents", headers=WORKER)).json()

    assert [d["name"] for d in mine] == ["mine.odt"]
    assert mine[0]["collection_name"] == "Collection de dev-user"
    assert mine[0]["summary"] == "Les étapes d'arrivée d'un agent."
    # An admin also gets the public one (visible to them) - never the other private collection.
    assert sorted(d["name"] for d in admin) == ["mine.odt", "public.odt"]


async def test_an_edit_request_starts_a_draft_for_the_runs_user_and_can_be_followed(client, queue):
    collection_id, document_id = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")

    created = await client.post(
        f"/api/internal/runs/{run_id}/edit-requests",
        json={"document_id": str(document_id), "prompt": "Ajoute un numéro d'urgence"},
        headers=WORKER,
    )

    assert created.status_code == 202
    assert created.json()["status"] == "pending"
    payload, task_id = queue.jobs[0]
    assert payload["prompt"] == "Ajoute un numéro d'urgence" and payload["user_id"] == "dev-user"
    followed = await client.get(f"/api/internal/runs/{run_id}/edit-requests/{document_id}", headers=WORKER)
    assert followed.status_code == 200 and followed.json()["status"] == "pending"
    # It is the same draft the user-facing API (and so the chat card) sees.
    assert (await client.get(f"/api/collections/{collection_id}/documents/{document_id}/draft")).status_code == 200
    async with async_session_factory() as session:
        assert await session.scalar(select(Task).where(Task.celery_task_id == task_id)) is not None


async def test_an_edit_request_follows_the_rights_of_the_runs_user_not_the_agents(client, queue):
    _, document_id = await _seed_document("someone", visibility=CollectionVisibility.PUBLIC)
    _, private_id = await _seed_document("someone")
    plain = await _seed_run("dev-user")
    admin = await _seed_run("dev-user", is_admin=True)

    def post(run_id, doc_id):
        return client.post(
            f"/api/internal/runs/{run_id}/edit-requests",
            json={"document_id": str(doc_id), "prompt": "Ajoute un numéro"},
            headers=WORKER,
        )

    assert (await post(plain, document_id)).status_code == 403  # visible, not editable
    assert (await post(admin, private_id)).status_code == 404  # not even visible
    assert (await post(admin, uuid.uuid4())).status_code == 404
    assert queue.jobs == []
    assert (await post(admin, document_id)).status_code == 202
    assert len(queue.jobs) == 1


async def test_a_second_edit_request_on_the_same_document_is_refused_with_a_message(client, queue):
    _, document_id = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")
    body = {"document_id": str(document_id), "prompt": "Ajoute un numéro"}
    await client.post(f"/api/internal/runs/{run_id}/edit-requests", json=body, headers=WORKER)

    again = await client.post(f"/api/internal/runs/{run_id}/edit-requests", json=body, headers=WORKER)

    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "draft_exists"
    assert "validez-le ou refusez-le" in again.json()["detail"]["message"]


async def test_the_agents_endpoints_need_the_workers_api_key_and_a_known_run(client, queue):
    _, document_id = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")
    body = {"document_id": str(document_id), "prompt": "Ajoute un numéro"}

    assert (await client.get(f"/api/internal/runs/{run_id}/editable-documents")).status_code in (401, 403)
    assert (await client.post(f"/api/internal/runs/{run_id}/edit-requests", json=body)).status_code in (401, 403)
    unknown = await client.get(f"/api/internal/runs/{uuid.uuid4()}/editable-documents", headers=WORKER)
    assert unknown.status_code == 404
    assert (
        await client.post(f"/api/internal/runs/{uuid.uuid4()}/edit-requests", json=body, headers=WORKER)
    ).status_code == 404
    assert queue.jobs == []


async def test_a_blank_prompt_is_rejected(client, queue):
    _, document_id = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")

    response = await client.post(
        f"/api/internal/runs/{run_id}/edit-requests",
        json={"document_id": str(document_id), "prompt": "  "},
        headers=WORKER,
    )

    assert response.status_code == 422


# -- the proposal travels with the answer -------------------------------------------------------


async def test_the_edit_proposal_is_stored_with_the_run_and_comes_back_with_its_message(client):
    run_id = await _seed_run("dev-user")
    proposal = {"collection_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()), "document_name": "procedure.odt"}

    stored = await client.patch(
        f"/api/internal/runs/{run_id}/result",
        json={"answer": "J'ai préparé une modification.", "citations": [], "edit_proposal": proposal},
        headers=WORKER,
    )
    assert stored.status_code == 200

    app.dependency_overrides[get_current_user] = _as_user("dev-user")
    run = (await client.get(f"/api/runs/{run_id}")).json()
    assert run["edit_proposal"] == proposal
    async with async_session_factory() as session:
        conversation_id = (await session.scalar(select(Run).where(Run.id == run_id))).conversation_id
    messages = (await client.get(f"/api/conversations/{conversation_id}/messages")).json()
    assistant = next(m for m in messages if m["role"] == "assistant")
    assert assistant["edit_proposal"] == proposal
    assert next(m for m in messages if m["role"] == "user")["edit_proposal"] is None


async def test_a_run_without_a_delegated_edit_has_no_proposal(client):
    run_id = await _seed_run("dev-user")
    await client.patch(
        f"/api/internal/runs/{run_id}/result", json={"answer": "Voici.", "citations": []}, headers=WORKER
    )
    app.dependency_overrides[get_current_user] = _as_user("dev-user")

    assert (await client.get(f"/api/runs/{run_id}")).json()["edit_proposal"] is None


# -- citations carry the revision of a living document ------------------------------------------


async def _cite(client, document_id: uuid.UUID, collection_id: uuid.UUID) -> dict:
    run_id = await _seed_run("dev-user")
    citation = {
        "evidence_id": "abc",
        "source": "procedure.odt",
        "vdb_id": str(collection_id),
        "tool": "search",
        "evidence_kind": "chunk",
        "document_id": str(document_id),
        "page_number": 1,
    }
    await client.patch(
        f"/api/internal/runs/{run_id}/result",
        json={"answer": "Voir [abc].", "citations": [citation]},
        headers=WORKER,
    )
    async with async_session_factory() as session:
        return (await session.scalar(select(Run).where(Run.id == run_id))).citations[0]


async def test_a_citation_of_a_living_document_says_which_revision_the_answer_came_from(client):
    collection_id, document_id = await _seed_document("dev-user")
    async with async_session_factory() as session:
        session.add(
            DocumentRevision(
                document_id=document_id,
                number=2,
                storage_key="documents/x/v2.odt",
                filename="procedure.odt",
                format="odt",
                origin=RevisionOrigin.CHAT,
            )
        )
        await session.commit()

    citation = await _cite(client, document_id, collection_id)

    assert citation["document_revision"] == 2
    assert citation["source_id"]


async def test_a_citation_of_an_ordinary_document_has_no_revision(client):
    collection_id, document_id = await _seed_document("dev-user", kind=DocumentKind.STANDARD, name="plain.pdf")

    citation = await _cite(client, document_id, collection_id)

    assert "document_revision" not in citation
    assert citation["source_id"]
