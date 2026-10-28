import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.repositories.collection_repository import CollectionRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.qa_pair_repository import QaPairRepository
from app.schemas.internal_evaluation import EvaluationQaPairOut, EvaluationRunCreate

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    dependencies=[Depends(require_worker_api_key)],
)

# A results.json holds one entry per QA pair (question, answers, contexts, scores) and a
# report.html one table row per pair - a few MB even for a large collection. Anything
# past this is a promptfoo output gone wrong, not something to store as-is.
_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024


@router.get(
    "/collections/{collection_id}/qa-pairs",
    summary="List every QA pair of a collection, validated or not - what worker/evaluation "
    "replays retrieval against, grouping its aggregates by EvaluationQaPairOut.validated",
    response_model=list[EvaluationQaPairOut],
)
async def list_qa_pairs_for_evaluation(
    collection_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[EvaluationQaPairOut]:
    if await CollectionRepository(db).get_by_id(collection_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    pairs = await QaPairRepository(db).list_by_collection(collection_id)
    return [
        EvaluationQaPairOut(
            id=pair.id,
            question=pair.question,
            answer=pair.answer,
            document_id=pair.document_id,
            validated=pair.validated,
            golden=pair.golden,
            relevant_document_ids=[uuid.UUID(i) for i in (pair.relevant_document_ids or [])],
        )
        for pair in pairs
    ]


@router.post(
    "/collections/{collection_id}/evaluation-runs",
    summary="Record a completed promptfoo evaluation run (see #11) - its metadata and both "
    "artifacts (results.json + report.html) in one request, so a run never exists without them",
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_run(
    collection_id: uuid.UUID,
    body: Annotated[EvaluationRunCreate, Form()],
    results: Annotated[UploadFile, File(description="promptfoo's results.json")],
    report: Annotated[UploadFile, File(description="promptfoo's report.html")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    if await CollectionRepository(db).get_by_id(collection_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    results_bytes = await results.read()
    report_bytes = await report.read()
    if len(results_bytes) > _MAX_ARTIFACT_BYTES or len(report_bytes) > _MAX_ARTIFACT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Evaluation artifacts exceed the size limit",
        )
    # Store both artifacts before creating the row: a run must never be visible without them
    # (the list endpoint reads results.json to compute its scores). If storage fails, no row
    # is created; if the commit fails, the objects are orphaned but harmless (see delete_run).
    run_id = uuid.uuid4()
    results_key = f"evaluations/{run_id}/results.json"
    report_key = f"evaluations/{run_id}/report.html"
    await asyncio.to_thread(storage.put_object, results_key, results_bytes, "application/json")
    await asyncio.to_thread(storage.put_object, report_key, report_bytes, "text/html")
    run = await EvaluationRepository(db).create_run(
        collection_id,
        body.model_dump(mode="python"),
        run_id=run_id,
        results_json_key=results_key,
        report_html_key=report_key,
    )
    await db.commit()
    return {"status": "ok", "id": str(run.id)}


@router.get(
    "/collections/{collection_id}/evaluation-runs/exists",
    summary="Check whether an evaluation run already exists for this (content_hash, llm_model) pair - "
    "lets the worker skip re-evaluating an unchanged collection with the same model (see #11)",
)
async def find_evaluation_run(
    collection_id: uuid.UUID,
    content_hash: str,
    llm_model: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str | None]:
    existing_id = await EvaluationRepository(db).find_existing(collection_id, content_hash, llm_model)
    return {"id": str(existing_id) if existing_id else None}
