import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.chunk import Chunk
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.evaluation import EvaluationResultSource, EvaluationRun
from app.models.qa import QaOrigin, QaPair

API_KEY = "test-worker-key"


@pytest.fixture(autouse=True)
def _set_worker_api_key(monkeypatch):
    monkeypatch.setattr(worker_auth._worker_settings, "WORKER_API_KEY", API_KEY)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as async_client:
        yield async_client
    async with async_session_factory() as session:
        await session.execute(delete(EvaluationRun))
        await session.execute(delete(QaPair))
        await session.execute(delete(Chunk))
        await session.execute(delete(Document))
        await session.execute(delete(Collection))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def _run_payload(**overrides) -> dict:
    payload = {
        "k": 5,
        "pair_count": 0,
        "llm_model": "test-model",
        "snapshot_chunking_strategy": "paragraph",
        "snapshot_chunk_size": 500,
        "snapshot_chunk_overlap": 50,
        "snapshot_embedding_model": "text-embedding-3-small",
        "precision_at_k": 0.0,
        "recall_at_k": 0.0,
        "mrr": 0.0,
        "ndcg": 0.0,
        "validated_pair_count": 0,
        "validated_precision_at_k": None,
        "validated_recall_at_k": None,
        "validated_mrr": None,
        "validated_ndcg": None,
        "unvalidated_pair_count": 0,
        "unvalidated_precision_at_k": None,
        "unvalidated_recall_at_k": None,
        "unvalidated_mrr": None,
        "unvalidated_ndcg": None,
        "results": [],
    }
    payload.update(overrides)
    return payload


async def _create_collection_with_document() -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(collection_id=collection.id, name="handbook.pdf", type="file", storage_key="k")
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def test_list_qa_pairs_for_evaluation_includes_validated_and_not(client):
    collection_id, document_id = await _create_collection_with_document()
    async with async_session_factory() as session:
        session.add_all(
            [
                QaPair(
                    collection_id=collection_id,
                    document_id=document_id,
                    question="Validated?",
                    answer="Yes.",
                    origin=QaOrigin.MANUAL,
                    validated=True,
                ),
                QaPair(
                    collection_id=collection_id,
                    document_id=document_id,
                    question="Unvalidated?",
                    answer="Maybe.",
                    origin=QaOrigin.GENERATED,
                    validated=False,
                ),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/internal/collections/{collection_id}/qa-pairs", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_question = {row["question"]: row for row in body}
    assert by_question["Validated?"]["validated"] is True
    assert by_question["Unvalidated?"]["validated"] is False


async def test_list_qa_pairs_for_evaluation_for_unknown_collection_returns_404(client):
    response = await client.get(f"/api/internal/collections/{uuid.uuid4()}/qa-pairs", headers=_headers())
    assert response.status_code == 404


async def test_get_document_chunk_count(client):
    _, document_id = await _create_collection_with_document()
    async with async_session_factory() as session:
        session.add_all(
            [
                Chunk(document_id=document_id, index=0, text="a", token_count=1),
                Chunk(document_id=document_id, index=1, text="b", token_count=1),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/internal/documents/{document_id}/chunk-count", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {"count": 2}


async def test_get_document_chunk_count_not_found(client):
    response = await client.get(f"/api/internal/documents/{uuid.uuid4()}/chunk-count", headers=_headers())
    assert response.status_code == 404


async def test_create_evaluation_run_persists_run_and_results(client):
    collection_id, document_id = await _create_collection_with_document()
    async with async_session_factory() as session:
        qa_pair = QaPair(
            collection_id=collection_id,
            document_id=document_id,
            question="What is the policy?",
            answer="2 days/week.",
            origin=QaOrigin.MANUAL,
            validated=True,
        )
        session.add(qa_pair)
        await session.commit()
        qa_pair_id = qa_pair.id

    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs",
        headers=_headers(),
        json=_run_payload(
            pair_count=1,
            precision_at_k=0.8,
            recall_at_k=0.6,
            mrr=1.0,
            ndcg=0.9,
            validated_pair_count=1,
            validated_precision_at_k=0.8,
            validated_recall_at_k=0.6,
            validated_mrr=1.0,
            validated_ndcg=0.9,
            results=[
                {
                    "qa_pair_id": str(qa_pair_id),
                    "question": "What is the policy?",
                    "expected_answer": "2 days/week.",
                    "generated_answer": "Telework is 2 days/week.",
                    "precision_at_k": 0.8,
                    "recall_at_k": 0.6,
                    "reciprocal_rank": 1.0,
                    "ndcg": 0.9,
                    "validated": True,
                    "retrieved_sources": ["handbook.pdf#0", "handbook.pdf#1"],
                }
            ],
        ),
    )

    assert response.status_code == 201
    run_id = uuid.UUID(response.json()["id"])

    async with async_session_factory() as session:
        run = await session.get(EvaluationRun, run_id, options=[selectinload(EvaluationRun.results)])
        assert run is not None
        assert run.pair_count == 1
        assert run.precision_at_k == 0.8
        assert run.validated_pair_count == 1
        assert run.validated_precision_at_k == 0.8
        assert run.unvalidated_pair_count == 0
        assert run.unvalidated_precision_at_k is None
        assert len(run.results) == 1
        result = run.results[0]
        assert result.qa_pair_id == qa_pair_id
        assert result.validated is True
        sources = (
            (
                await session.execute(
                    select(EvaluationResultSource).where(EvaluationResultSource.evaluation_result_id == result.id)
                )
            )
            .scalars()
            .all()
        )
        assert {source.source for source in sources} == {"handbook.pdf#0", "handbook.pdf#1"}


async def test_create_evaluation_run_for_unknown_collection_returns_404(client):
    response = await client.post(
        f"/api/internal/collections/{uuid.uuid4()}/evaluation-runs", headers=_headers(), json=_run_payload()
    )
    assert response.status_code == 404
