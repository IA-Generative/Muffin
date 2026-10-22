import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.security import worker_auth
from app.db import async_session_factory
from app.main import app
from app.models.collection import Collection, CollectionSettings
from app.models.document import Document
from app.models.evaluation import EvaluationRun
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
        await session.execute(delete(Document))
        await session.execute(delete(Collection))
        await session.commit()


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def _run_payload(**overrides) -> dict:
    payload = {
        "k": 5,
        "pair_count": 1,
        "llm_model": "judge-model",
        "content_hash": "abc123",
        "snapshot_chunking_strategy": "paragraph",
        "snapshot_chunk_size": 500,
        "snapshot_chunk_overlap": 50,
        "snapshot_embedding_model": "text-embedding-3-small",
        "golden_pair_count": 0,
        "validated_pair_count": 1,
        "unvalidated_pair_count": 0,
    }
    payload.update(overrides)
    return payload


async def _create_collection_with_document() -> tuple[uuid.UUID, uuid.UUID]:
    async with async_session_factory() as session:
        collection = Collection(owner_id="dev-user", name="Policies", description="")
        collection.settings = CollectionSettings(embedding_model="text-embedding-3-small")
        session.add(collection)
        await session.flush()
        document = Document(
            collection_id=collection.id,
            name="handbook.pdf",
            type="file",
            storage_key="k",
        )
        session.add(document)
        await session.commit()
        return collection.id, document.id


async def _create_run(client, collection_id: uuid.UUID) -> uuid.UUID:
    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs",
        headers=_headers(),
        json=_run_payload(),
    )
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


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


async def test_create_evaluation_run_persists_metadata_only(client):
    collection_id, _ = await _create_collection_with_document()

    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs",
        headers=_headers(),
        json=_run_payload(golden_pair_count=1, unvalidated_pair_count=2, validated_pair_count=0),
    )

    assert response.status_code == 201
    run_id = uuid.UUID(response.json()["id"])

    async with async_session_factory() as session:
        run = await session.get(EvaluationRun, run_id)
        assert run is not None
        assert run.pair_count == 1
        assert run.llm_model == "judge-model"
        assert run.golden_pair_count == 1
        assert run.validated_pair_count == 0
        assert run.unvalidated_pair_count == 2
        assert run.content_hash == "abc123"
        # No artifacts yet - they follow via the artifacts endpoint.
        assert run.results_json_key is None
        assert run.report_html_key is None


async def test_create_evaluation_run_for_unknown_collection_returns_404(client):
    response = await client.post(
        f"/api/internal/collections/{uuid.uuid4()}/evaluation-runs",
        headers=_headers(),
        json=_run_payload(),
    )
    assert response.status_code == 404


async def test_upload_artifacts_stores_both_files_and_references_them(client, monkeypatch):
    stored: dict[str, tuple[bytes, str]] = {}
    monkeypatch.setattr(
        "app.core.storage.put_object",
        lambda key, data, content_type: stored.update({key: (data, content_type)}),
    )
    collection_id, _ = await _create_collection_with_document()
    run_id = await _create_run(client, collection_id)

    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs/{run_id}/artifacts",
        headers=_headers(),
        files={
            "results": ("results.json", b'{"results": {"results": []}}', "application/json"),
            "report": ("report.html", b"<html>report</html>", "text/html"),
        },
    )

    assert response.status_code == 201
    assert stored == {
        f"evaluations/{run_id}/results.json": (b'{"results": {"results": []}}', "application/json"),
        f"evaluations/{run_id}/report.html": (b"<html>report</html>", "text/html"),
    }
    async with async_session_factory() as session:
        run = await session.get(EvaluationRun, run_id)
        assert run.results_json_key == f"evaluations/{run_id}/results.json"
        assert run.report_html_key == f"evaluations/{run_id}/report.html"


async def test_upload_artifacts_for_unknown_run_returns_404(client):
    collection_id, _ = await _create_collection_with_document()

    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs/{uuid.uuid4()}/artifacts",
        headers=_headers(),
        files={
            "results": ("results.json", b"{}", "application/json"),
            "report": ("report.html", b"<html></html>", "text/html"),
        },
    )

    assert response.status_code == 404


async def test_upload_artifacts_for_run_of_another_collection_returns_404(client):
    collection_id, _ = await _create_collection_with_document()
    other_collection_id, _ = await _create_collection_with_document()
    run_id = await _create_run(client, collection_id)

    response = await client.post(
        f"/api/internal/collections/{other_collection_id}/evaluation-runs/{run_id}/artifacts",
        headers=_headers(),
        files={
            "results": ("results.json", b"{}", "application/json"),
            "report": ("report.html", b"<html></html>", "text/html"),
        },
    )

    assert response.status_code == 404


async def test_upload_artifacts_rejects_oversized_file(client):
    collection_id, _ = await _create_collection_with_document()
    run_id = await _create_run(client, collection_id)

    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs/{run_id}/artifacts",
        headers=_headers(),
        files={
            "results": ("results.json", b"x" * (50 * 1024 * 1024 + 1), "application/json"),
            "report": ("report.html", b"<html></html>", "text/html"),
        },
    )

    assert response.status_code == 413
