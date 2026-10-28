import json
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.security import worker_auth
from app.core.security.factory import get_current_user
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings, CollectionVisibility
from app.models.document import Document, DocumentStatus, DocumentType
from app.models.evaluation import EvaluationRun
from app.models.qa import QaPair
from app.repositories.qa_pair_repository import QaPairRepository
from tests.routers.test_collections import _as_user

API_KEY = "test-worker-key"
WORKER = {"X-API-Key": API_KEY}
VECTORS = "app.services.vector_store"


@pytest.fixture(autouse=True)
def _worker_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_current_user, None)
    async with async_session_factory() as session:
        await session.execute(delete(EvaluationRun))
        await session.execute(delete(QaPair))
        await session.execute(delete(Document))
        await session.execute(delete(Collection))
        await session.commit()


async def _collection(owner="dev-user", visibility=CollectionVisibility.PRIVATE, documents=("a.pdf", "b.pdf")):
    """A collection and its documents' ids, in the order given."""
    async with async_session_factory() as session:
        collection = Collection(owner_id=owner, name="Procédures", description="", visibility=visibility)
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        ids = []
        for name in documents:
            document = Document(
                collection_id=collection.id,
                name=name,
                type=DocumentType.FILE,
                storage_key=f"documents/{collection.id}/{name}",
                status=DocumentStatus.INDEXED,
            )
            session.add(document)
            await session.flush()
            ids.append(document.id)
        await session.commit()
        return collection.id, ids


async def _generated_pair(collection_id, document_id=None, validated=False) -> uuid.UUID:
    async with async_session_factory() as session:
        pair = await QaPairRepository(session).create(collection_id, document_id, "Question générée ?", "Réponse.")
        pair.validated = validated
        await session.commit()
        return pair.id


def _url(collection_id, suffix=""):
    return f"/api/collections/{collection_id}/qa-pairs{suffix}"


async def _golden(client, collection_id, relevant=(), question="Combien de jours de télétravail ?", golden=True):
    return await client.post(
        _url(collection_id),
        json={
            "question": question,
            "answer": "Deux jours par semaine.",
            "golden": golden,
            "relevant_document_ids": [str(i) for i in relevant],
        },
    )


# -- writing a golden pair ----------------------------------------------------------------------


async def test_a_golden_pair_is_stored_validated_and_never_embedded(client):
    collection_id, (doc_a, doc_b) = await _collection()

    with patch(f"{VECTORS}.upsert_qa_embedding") as embed:
        response = await _golden(client, collection_id, [doc_a, doc_b])

    assert response.status_code == 201
    body = response.json()
    assert (body["golden"], body["validated"], body["origin"]) == (True, True, "manual")
    assert body["source"] == "a.pdf"
    assert [d["name"] for d in body["relevant_documents"]] == ["a.pdf", "b.pdf"]
    embed.assert_not_called()  # the whole point: nothing for the retriever to match
    async with async_session_factory() as session:
        pair = await session.get(QaPair, uuid.UUID(body["id"]))
    assert pair.golden and pair.validated
    assert pair.document_id == doc_a  # the main document is the first one
    assert pair.relevant_document_ids == [str(doc_a), str(doc_b)]


async def test_the_list_shows_golden_pairs_with_their_documents(client):
    collection_id, (doc_a, doc_b) = await _collection()
    await _generated_pair(collection_id, doc_a)
    await _golden(client, collection_id, [doc_b])

    pairs = (await client.get(_url(collection_id))).json()

    by_golden = {p["golden"]: p for p in pairs}
    assert by_golden[True]["relevant_documents"] == [{"id": str(doc_b), "name": "b.pdf"}]
    assert by_golden[False]["relevant_documents"] == [] and by_golden[False]["source"] == "a.pdf"


async def test_a_golden_pair_without_a_document_is_kept_but_has_nothing_to_score_against(client):
    collection_id, _ = await _collection()

    response = await _golden(client, collection_id, [])

    assert response.status_code == 201
    assert response.json()["relevant_documents"] == [] and response.json()["source"] is None


async def test_a_duplicate_relevant_document_is_kept_once(client):
    collection_id, (doc_a, _) = await _collection()

    response = await _golden(client, collection_id, [doc_a, doc_a])

    assert [d["name"] for d in response.json()["relevant_documents"]] == ["a.pdf"]


async def test_only_this_collections_documents_can_be_relevant(client):
    collection_id, _ = await _collection()
    _, (foreign_doc,) = await _collection(documents=("elsewhere.pdf",))

    response = await _golden(client, collection_id, [foreign_doc])

    assert response.status_code == 422
    async with async_session_factory() as session:
        assert (await session.scalars(select(QaPair))).all() == []


@pytest.mark.parametrize("body", [{"question": "  ", "answer": "x"}, {"question": "q", "answer": ""}, {"answer": "x"}])
async def test_a_golden_pair_needs_a_question_and_an_answer(client, body):
    collection_id, _ = await _collection()

    assert (await client.post(_url(collection_id), json=body)).status_code == 422


async def test_only_the_owner_writes_golden_pairs(client):
    collection_id, (doc_a, _) = await _collection(owner="owner", visibility=CollectionVisibility.PUBLIC)
    app.dependency_overrides[get_current_user] = _as_user("viewer", "viewer@example.com")

    response = await _golden(client, collection_id, [doc_a])

    assert response.status_code == 404  # readable, so listed - but never writable
    assert (await client.get(_url(collection_id))).status_code == 200
    async with async_session_factory() as session:
        assert (await session.scalars(select(QaPair))).all() == []


# -- a golden pair is never something the retriever hands back ----------------------------------


async def test_the_qa_tier_never_resolves_a_golden_pair_even_if_a_vector_pointed_at_it(client):
    collection_id, (doc_a, _) = await _collection()
    generated_id = await _generated_pair(collection_id, doc_a, validated=True)
    golden_id = uuid.UUID((await _golden(client, collection_id, [doc_a])).json()["id"])

    async with async_session_factory() as session:
        found = await QaPairRepository(session).get_by_ids([generated_id, golden_id])

    assert [pair.id for pair in found] == [generated_id]


# -- removing and validating pairs --------------------------------------------------------------


async def test_removing_a_generated_pair_also_removes_its_embedding(client):
    collection_id, (doc_a, _) = await _collection()
    pair_id = await _generated_pair(collection_id, doc_a)

    with patch(f"{VECTORS}.delete_qa_embedding") as remove:
        response = await client.delete(_url(collection_id, f"/{pair_id}"))

    assert response.status_code == 204
    remove.assert_called_once_with(collection_id, pair_id)
    async with async_session_factory() as session:
        assert await session.get(QaPair, pair_id) is None


async def test_removing_a_golden_pair_has_no_embedding_to_remove(client):
    collection_id, (doc_a, _) = await _collection()
    golden_id = uuid.UUID((await _golden(client, collection_id, [doc_a])).json()["id"])

    with patch(f"{VECTORS}.delete_qa_embedding") as remove:
        response = await client.delete(_url(collection_id, f"/{golden_id}"))

    assert response.status_code == 204
    remove.assert_not_called()
    assert (await client.get(_url(collection_id))).json() == []


async def test_a_pair_of_another_collection_or_a_stranger_is_not_found(client):
    collection_id, (doc_a, _) = await _collection()
    other_id, (other_doc,) = await _collection(documents=("o.pdf",))
    pair_id = await _generated_pair(other_id, other_doc)

    assert (await client.delete(_url(collection_id, f"/{pair_id}"))).status_code == 404
    assert (await client.delete(_url(collection_id, f"/{uuid.uuid4()}"))).status_code == 404

    app.dependency_overrides[get_current_user] = _as_user("stranger", "stranger@example.com")
    assert (await client.delete(_url(other_id, f"/{pair_id}"))).status_code == 404
    async with async_session_factory() as session:
        assert await session.get(QaPair, pair_id) is not None


async def test_validating_a_generated_pair_is_saved(client):
    collection_id, (doc_a, _) = await _collection()
    pair_id = await _generated_pair(collection_id, doc_a)

    assert (await client.patch(_url(collection_id, f"/{pair_id}"), json={"validated": True})).status_code == 204
    assert (await client.get(_url(collection_id))).json()[0]["validated"] is True
    assert (await client.patch(_url(collection_id, f"/{pair_id}"), json={"validated": False})).status_code == 204
    assert (await client.get(_url(collection_id))).json()[0]["validated"] is False


async def test_a_golden_pair_stays_validated(client):
    collection_id, (doc_a, _) = await _collection()
    golden_id = (await _golden(client, collection_id, [doc_a])).json()["id"]

    response = await client.patch(_url(collection_id, f"/{golden_id}"), json={"validated": False})

    assert response.status_code == 409 and response.json()["detail"]["code"] == "golden_always_validated"
    assert (await client.get(_url(collection_id))).json()[0]["validated"] is True


# -- evaluation ---------------------------------------------------------------------------------


async def test_the_evaluation_worker_is_given_the_golden_flag_and_every_relevant_document(client):
    collection_id, (doc_a, doc_b) = await _collection()
    await _generated_pair(collection_id, doc_a, validated=True)
    await _golden(client, collection_id, [doc_a, doc_b])

    pairs = (await client.get(f"/api/internal/collections/{collection_id}/qa-pairs", headers=WORKER)).json()

    golden = next(p for p in pairs if p["golden"])
    assert golden["relevant_document_ids"] == [str(doc_a), str(doc_b)] and golden["validated"] is True
    generated = next(p for p in pairs if not p["golden"])
    assert generated["relevant_document_ids"] == []


def _results_json(*tests):
    return {"results": {"results": list(tests)}}


def _test_row(question, factuality, context_faithfulness, golden):
    return {
        "vars": {"query": question, "reference": "x", "validated": True, "golden": golden},
        "response": {"output": "y", "metadata": {"sources": ["a.pdf#1"]}},
        "namedScores": {"factuality": factuality, "context_faithfulness": context_faithfulness},
    }


async def _run_with_artifact(client, monkeypatch, collection_id, tests, golden_pair_count):
    """Creates the run with its promptfoo artifact in one request, RustFS mocked out."""
    objects: dict[str, bytes] = {}
    monkeypatch.setattr("app.core.storage.put_object", lambda key, data, content_type: objects.update({key: data}))
    monkeypatch.setattr(
        "app.core.storage.get_object",
        lambda key: (objects[key], "application/json" if key.endswith(".json") else "text/html"),
    )
    created = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs",
        data={
            "pair_count": len(tests),
            "llm_model": "test-model",
            "content_hash": f"hash-{uuid.uuid4()}",
            "golden_pair_count": golden_pair_count,
            "validated_pair_count": len(tests) - golden_pair_count,
            "unvalidated_pair_count": 0,
        },
        files={
            "results": ("results.json", json.dumps(_results_json(*tests)).encode(), "application/json"),
            "report": ("report.html", b"<html></html>", "text/html"),
        },
        headers=WORKER,
    )
    assert created.status_code == 201
    return created.json()["id"]


async def test_an_evaluation_run_reports_its_golden_scores_apart(client, monkeypatch):
    collection_id, _ = await _collection()
    await _run_with_artifact(
        client,
        monkeypatch,
        collection_id,
        tests=[
            _test_row("Question générée ?", 0.5, 0.4, golden=False),
            _test_row("Question dorée ?", 1.0, 0.9, golden=True),
        ],
        golden_pair_count=1,
    )

    (run,) = (await client.get(f"/api/collections/{collection_id}/evaluations")).json()

    assert run["golden_metrics"] == {"factuality": 1.0, "context_faithfulness": 0.9}
    # the generated pairs' own, untouched by the golden one
    assert run["metrics"] == {"factuality": 0.5, "context_faithfulness": 0.4}
    # every pair, golden included: (0.5 + 1.0) / 2 and (0.4 + 0.9) / 2
    assert run["all_metrics"] == {"factuality": 0.75, "context_faithfulness": 0.65}


async def test_a_run_made_only_of_golden_pairs_has_no_global_aggregate(client, monkeypatch):
    collection_id, _ = await _collection()
    await _run_with_artifact(
        client,
        monkeypatch,
        collection_id,
        tests=[_test_row("Question dorée ?", 1.0, 0.9, golden=True)],
        golden_pair_count=1,
    )

    (run,) = (await client.get(f"/api/collections/{collection_id}/evaluations")).json()

    assert run["metrics"] is None
    assert run["golden_metrics"] == {"factuality": 1.0, "context_faithfulness": 0.9}
    # no reference pair, so the all-pairs average is the golden one
    assert run["all_metrics"] == {"factuality": 1.0, "context_faithfulness": 0.9}


# -- a reference pair, written by hand, is the opposite: the assistant answers from it --------------


SERVICE = "app.services.qa_pair_service"


async def test_a_reference_pair_is_stored_and_embedded_for_the_assistant(client):
    collection_id, (doc_a, _) = await _collection()

    with (
        patch(f"{SERVICE}.embed_text", return_value=[0.1, 0.2]) as embed,
        patch(f"{VECTORS}.upsert_qa_embedding") as upsert,
    ):
        response = await _golden(client, collection_id, [doc_a], golden=False)

    assert response.status_code == 201
    body = response.json()
    assert (body["golden"], body["validated"], body["origin"], body["source"]) == (False, True, "manual", "a.pdf")
    embed.assert_called_once_with("text-embedding-3-small", "Combien de jours de télétravail ?")
    upsert.assert_called_once()
    assert upsert.call_args.args[:3] == (collection_id, uuid.UUID(body["id"]), [0.1, 0.2])
    async with async_session_factory() as session:
        pair = await session.get(QaPair, uuid.UUID(body["id"]))
    assert not pair.golden and pair.relevant_document_ids is None and pair.document_id == doc_a


async def test_a_reference_pair_that_cannot_be_embedded_is_still_saved(client):
    collection_id, _ = await _collection()

    with (
        patch(f"{SERVICE}.embed_text", side_effect=RuntimeError("hub down")),
        patch(f"{VECTORS}.upsert_qa_embedding") as upsert,
    ):
        response = await _golden(client, collection_id, [], golden=False)

    assert response.status_code == 201
    upsert.assert_not_called()
    assert len((await client.get(_url(collection_id))).json()) == 1


async def test_only_a_golden_pair_can_name_several_documents(client):
    collection_id, (doc_a, doc_b) = await _collection()

    with patch(f"{SERVICE}.embed_text", return_value=[0.1]), patch(f"{VECTORS}.upsert_qa_embedding"):
        reference = await _golden(client, collection_id, [doc_a, doc_b], golden=False)
    golden = await _golden(client, collection_id, [doc_a, doc_b], golden=True)

    assert reference.status_code == 422 and golden.status_code == 201
