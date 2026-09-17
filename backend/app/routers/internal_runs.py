import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.worker_auth import require_worker_api_key
from app.db import get_db
from app.models.run import RunStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.run_repository import RunRepository
from app.schemas.internal_run import (
    AccessibleCollectionOut,
    InternalRunOut,
    RunErrorUpdate,
    RunEventCreate,
    RunResultUpdate,
    RunStateUpdate,
    RunStatusUpdate,
    SearchRequest,
    SearchResultOut,
)

router = APIRouter(prefix="/internal", tags=["Internal"], dependencies=[Depends(require_worker_api_key)])


def _to_out(run) -> InternalRunOut:  # noqa: ANN001
    return InternalRunOut(
        id=run.id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        message_id=run.message_id,
        query=run.query,
        status=run.status,
        cancel_requested=run.cancel_requested,
        plan_version=run.plan_version,
        replan_count=run.replan_count,
        research_plan=run.research_plan,
        budget=run.budget,
        pending_human_action=run.pending_human_action,
        answer=run.answer,
        citations=run.citations,
    )


@router.get(
    "/runs/{run_id}", summary="Fetch a run's full state for the worker to resume/act on", response_model=InternalRunOut
)
async def get_run(run_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> InternalRunOut:
    run = await RunRepository(db).get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _to_out(run)


@router.patch("/runs/{run_id}/status", summary="Report a run's status/current node/activity")
async def update_run_status(
    run_id: uuid.UUID, update: RunStatusUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.update_status(run, RunStatus(update.status), update.current_node, update.current_activity)
    await db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}/state", summary="Merge into a run's plan/budget/pending_human_action state")
async def update_run_state(
    run_id: uuid.UUID, update: RunStateUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.update_state(
        run, update.research_plan, update.budget, update.pending_human_action, update.plan_version, update.replan_count
    )
    await db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}/result", summary="Report a run's final answer and citations")
async def update_run_result(
    run_id: uuid.UUID, update: RunResultUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.set_result(run, update.answer, update.citations)
    await db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}/error", summary="Report a run failure")
async def update_run_error(
    run_id: uuid.UUID, update: RunErrorUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    run = await repository.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.set_error(run, update.error)
    await db.commit()
    return {"status": "ok"}


@router.post("/runs/{run_id}/events", summary="Record a structured progress event", status_code=status.HTTP_201_CREATED)
async def create_run_event(
    run_id: uuid.UUID, event: RunEventCreate, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, str]:
    repository = RunRepository(db)
    if await repository.get_by_id(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await repository.add_event(run_id, event.type, event.data, event.task_id)
    await db.commit()
    return {"status": "ok"}


@router.get(
    "/users/{user_id}/accessible-collections",
    summary="List the collections a user can reach - the only permission check the agent's VDB "
    "routing is allowed to trust (never the LLM, never the run payload)",
    response_model=list[AccessibleCollectionOut],
)
async def list_accessible_collections(
    user_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[AccessibleCollectionOut]:
    collections = await CollectionRepository(db).list_all_by_owner(user_id)
    return [
        AccessibleCollectionOut(
            id=collection.id,
            name=collection.name,
            description=collection.description,
            tags=[tag.tag for tag in collection.tags],
        )
        for collection in collections
    ]


@router.post(
    "/search",
    summary="Full-text search over the chunks of the given collections (Postgres today, "
    "not Qdrant - see docs/research-agent-plan.md)",
    response_model=list[SearchResultOut],
)
async def search(body: SearchRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> list[SearchResultOut]:
    rows = await ChunkRepository(db).search(body.collection_ids, body.query, body.limit)
    return [
        SearchResultOut(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_name=document_name,
            collection_id=collection_id,
            text=chunk.text,
            rank=rank,
        )
        for chunk, document_name, collection_id, rank in rows
    ]
