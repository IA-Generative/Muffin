import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

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
        "pair_count": 1,
        "llm_model": "judge-model",
        "content_hash": "abc123",
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


async def _create_run(
    client,
    collection_id: uuid.UUID,
    *,
    payload: dict | None = None,
    results: bytes = b'{"results": {"results": []}}',
    report: bytes = b"<html>report</html>",
) -> uuid.UUID:
    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs",
        headers=_headers(),
        data=payload or _run_payload(),
        files={
            "results": ("results.json", results, "application/json"),
            "report": ("report.html", report, "text/html"),
        },
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


async def test_create_evaluation_run_persists_metadata_and_artifacts(client, monkeypatch):
    stored: dict[str, tuple[bytes, str]] = {}
    monkeypatch.setattr(
        "app.core.storage.put_object",
        lambda key, data, content_type: stored.update({key: (data, content_type)}),
    )
    collection_id, _ = await _create_collection_with_document()

    run_id = await _create_run(
        client,
        collection_id,
        payload=_run_payload(golden_pair_count=1, unvalidated_pair_count=2, validated_pair_count=0),
    )

    assert stored == {
        f"evaluations/{run_id}/results.json": (b'{"results": {"results": []}}', "application/json"),
        f"evaluations/{run_id}/report.html": (b"<html>report</html>", "text/html"),
    }
    async with async_session_factory() as session:
        run = await session.get(EvaluationRun, run_id)
        assert run is not None
        assert run.pair_count == 1
        assert run.llm_model == "judge-model"
        assert run.golden_pair_count == 1
        assert run.validated_pair_count == 0
        assert run.unvalidated_pair_count == 2
        assert run.content_hash == "abc123"
        # The row is only written once both artifacts are stored.
        assert run.results_json_key == f"evaluations/{run_id}/results.json"
        assert run.report_html_key == f"evaluations/{run_id}/report.html"


async def test_create_evaluation_run_for_unknown_collection_returns_404(client):
    response = await client.post(
        f"/api/internal/collections/{uuid.uuid4()}/evaluation-runs",
        headers=_headers(),
        data=_run_payload(),
        files={
            "results": ("results.json", b"{}", "application/json"),
            "report": ("report.html", b"<html></html>", "text/html"),
        },
    )
    assert response.status_code == 404


async def test_create_evaluation_run_rejects_oversized_artifact(client):
    collection_id, _ = await _create_collection_with_document()

    response = await client.post(
        f"/api/internal/collections/{collection_id}/evaluation-runs",
        headers=_headers(),
        data=_run_payload(),
        files={
            "results": ("results.json", b"x" * (50 * 1024 * 1024 + 1), "application/json"),
            "report": ("report.html", b"<html></html>", "text/html"),
        },
    )

    assert response.status_code == 413


async def test_create_evaluation_run_creates_no_row_when_storage_fails(client, monkeypatch):
    def boom(key, data, content_type):
        raise RuntimeError("RustFS is down")

    monkeypatch.setattr("app.core.storage.put_object", boom)
    collection_id, _ = await _create_collection_with_document()

    with pytest.raises(RuntimeError, match="RustFS is down"):
        await client.post(
            f"/api/internal/collections/{collection_id}/evaluation-runs",
            headers=_headers(),
            data=_run_payload(),
            files={
                "results": ("results.json", b"{}", "application/json"),
                "report": ("report.html", b"<html></html>", "text/html"),
            },
        )

    async with async_session_factory() as session:
        runs = (await session.execute(select(EvaluationRun))).scalars().all()
        assert runs == []
