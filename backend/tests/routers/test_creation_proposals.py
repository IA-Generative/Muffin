import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionVisibility
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.document_revision import DocumentRevision
from app.models.run import Run
from app.models.task import Task
from tests.routers.test_edit_delegation import API_KEY, WORKER, _as_user, _seed_document, _seed_run

LIVING = "app.services.living_document_service"


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
        await session.commit()


@pytest.fixture
def stored():
    """The object store and the processing queue, faked: records what was stored."""
    objects: dict[str, bytes] = {}
    with (
        patch(f"{LIVING}.storage.put_object", lambda key, data, content_type="": objects.__setitem__(key, data)),
        patch(f"{LIVING}.enqueue_process_document", side_effect=lambda _id: str(uuid.uuid4())) as process,
    ):
        objects["process"] = process  # type: ignore[assignment]
        yield objects


def _proposal(collection_id, **overrides):
    proposal = {
        "kind": "create",
        "status": "pending",
        "collection_id": str(collection_id),
        "collection_name": "Procédures",
        "name": "Accueil des nouveaux agents",
        "content": "# Accueil des nouveaux agents\n\nBienvenue.\n",
    }
    proposal.update(overrides)
    return proposal


async def _propose(client, run_id, proposal) -> None:
    stored_ok = await client.patch(
        f"/api/internal/runs/{run_id}/result",
        json={"answer": "J'ai rédigé un document.", "citations": [], "edit_proposal": proposal},
        headers=WORKER,
    )
    assert stored_ok.status_code == 200


async def _run_proposal(run_id) -> dict:
    async with async_session_factory() as session:
        return (await session.scalar(select(Run).where(Run.id == run_id))).edit_proposal


async def _documents(collection_id) -> list[Document]:
    async with async_session_factory() as session:
        return list(await session.scalars(select(Document).where(Document.collection_id == collection_id)))


async def test_the_agent_is_offered_only_the_collections_its_user_may_add_documents_to(client):
    await _seed_document("dev-user", name="a.odt")
    await _seed_document("dev-user", name="b.odt", temporary=True)
    await _seed_document("someone", name="public.odt", visibility=CollectionVisibility.PUBLIC)
    await _seed_document("someone", name="private.odt")
    run_id = await _seed_run("dev-user")
    admin_run_id = await _seed_run("dev-user", is_admin=True)

    mine = (await client.get(f"/api/internal/runs/{run_id}/editable-collections", headers=WORKER)).json()
    admin = (await client.get(f"/api/internal/runs/{admin_run_id}/editable-collections", headers=WORKER)).json()

    assert [c["name"] for c in mine] == ["Collection de dev-user"]
    # An administrator also gets the public one - never another user's private collection.
    assert sorted(c["name"] for c in admin) == ["Collection de dev-user", "Collection de someone"]
    assert (await client.get(f"/api/internal/runs/{run_id}/editable-collections")).status_code == 401
    assert (
        await client.get(f"/api/internal/runs/{uuid.uuid4()}/editable-collections", headers=WORKER)
    ).status_code == 404


async def test_validating_creates_the_markdown_document_as_a_chat_revision(client, stored):
    collection_id, _ = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")
    await _propose(client, run_id, _proposal(collection_id))

    response = await client.post(f"/api/runs/{run_id}/creation/validate")

    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Accueil des nouveaux agents.md" and created["kind"] == "living"
    stored["process"].assert_called_once()  # the new document is indexed like any other
    documents = {d.name: d for d in await _documents(collection_id)}
    assert "Accueil des nouveaux agents.md" in documents
    async with async_session_factory() as session:
        revision = await session.scalar(
            select(DocumentRevision).where(DocumentRevision.document_id == uuid.UUID(created["id"]))
        )
    assert (revision.number, revision.origin.value, revision.format) == (1, "chat", "md")
    assert stored[revision.storage_key] == b"# Accueil des nouveaux agents\n\nBienvenue.\n"
    # The proposal now says what happened, so the card and a reload agree.
    proposal = await _run_proposal(run_id)
    assert (proposal["status"], proposal["document_id"]) == ("created", created["id"])


async def test_a_proposal_cannot_be_created_twice(client, stored):
    collection_id, _ = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")
    await _propose(client, run_id, _proposal(collection_id))
    await client.post(f"/api/runs/{run_id}/creation/validate")

    again = await client.post(f"/api/runs/{run_id}/creation/validate")
    refused = await client.post(f"/api/runs/{run_id}/creation/refuse")

    assert again.status_code == 409 and again.json()["detail"]["code"] == "no_pending_creation"
    assert refused.status_code == 409
    # One document created, plus the seeded one.
    assert len(await _documents(collection_id)) == 2


async def test_refusing_creates_nothing_and_closes_the_proposal(client, stored):
    collection_id, _ = await _seed_document("dev-user")
    run_id = await _seed_run("dev-user")
    await _propose(client, run_id, _proposal(collection_id))

    response = await client.post(f"/api/runs/{run_id}/creation/refuse")

    assert response.status_code == 204
    assert len(await _documents(collection_id)) == 1
    assert (await _run_proposal(run_id))["status"] == "refused"
    assert (await client.post(f"/api/runs/{run_id}/creation/validate")).status_code == 409
    stored["process"].assert_not_called()


async def test_only_the_runs_owner_can_decide_and_only_where_they_may_edit(client, stored):
    collection_id, _ = await _seed_document("owner")
    run_id = await _seed_run("owner")
    await _propose(client, run_id, _proposal(collection_id))

    app.dependency_overrides[get_current_user] = _as_user("stranger")
    stranger = await client.post(f"/api/runs/{run_id}/creation/validate")
    assert stranger.status_code == 404
    assert (await client.post(f"/api/runs/{run_id}/creation/refuse")).status_code == 404

    # Someone whose own run proposes a collection they may not edit gets nothing created either.
    foreign_run_id = await _seed_run("stranger")
    await _propose(client, foreign_run_id, _proposal(collection_id))
    refused = await client.post(f"/api/runs/{foreign_run_id}/creation/validate")
    assert refused.status_code in (403, 404)
    assert len(await _documents(collection_id)) == 1
    assert (await _run_proposal(foreign_run_id))["status"] == "pending"


async def test_a_run_without_a_creation_proposal_has_nothing_to_validate(client, stored):
    run_id = await _seed_run("dev-user")
    assert (await client.post(f"/api/runs/{run_id}/creation/validate")).status_code == 409

    # An edit proposal (the other kind) is not a creation either.
    await _propose(
        client,
        run_id,
        {"collection_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()), "document_name": "procedure.odt"},
    )
    assert (await client.post(f"/api/runs/{run_id}/creation/validate")).status_code == 409
