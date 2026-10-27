import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.core.sharing import SharingNotConfiguredError
from app.db import get_db
from app.routers import internal_llm
from app.schemas.collection import (
    ChunkOut,
    CollectionCreate,
    CollectionOut,
    CollectionSettingsUpdate,
    CollectionUpdate,
    EntityMentionOut,
    EntityOut,
    GroundednessStatsOut,
    IndexingEstimateOut,
    IndexingEstimateRequest,
    QaPairOut,
    RelationOut,
    ShareCreate,
    ShareOut,
    VisibilityUpdate,
)
from app.schemas.evaluation import (
    EvaluationResultOut,
    EvaluationRunOut,
    EvaluationStatusOut,
    EvaluationTriggerRequest,
)
from app.schemas.feedback import FeedbackStatsOut
from app.schemas.pagination import Page, PaginationParams
from app.services.collection_hierarchy_service import (
    HierarchyCycleError,
    HierarchyError,
    HierarchyOwnerMismatchError,
    TemporaryCollectionHierarchyError,
)
from app.services.collection_service import (
    AlreadyInvitedError,
    CollectionNotFoundError,
    CollectionService,
    InvalidPipelineWindowsError,
    ParentCollectionNotFoundError,
    ShareNotFoundError,
)
from app.services.evaluation_service import (
    CollectionNotFoundError as EvaluationCollectionNotFoundError,
)
from app.services.evaluation_service import (
    EvaluationArtifactNotFoundError,
    EvaluationRunNotFoundError,
    EvaluationService,
)

router = APIRouter(tags=["Collections"])

_HIERARCHY_ERROR_DETAILS: dict[type[HierarchyError], str] = {
    HierarchyCycleError: "A collection cannot be moved under itself or one of its sub-collections",
    HierarchyOwnerMismatchError: "A sub-collection must have the same owner as its parent",
    TemporaryCollectionHierarchyError: "Temporary collections cannot be part of a hierarchy",
}


def _hierarchy_http_error(error: HierarchyError | ParentCollectionNotFoundError) -> HTTPException:
    if isinstance(error, ParentCollectionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent collection not found")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_HIERARCHY_ERROR_DETAILS[type(error)])


def get_collection_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CollectionService:
    return CollectionService(db)


def get_evaluation_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EvaluationService:
    return EvaluationService(db)


ServiceDep = Annotated[CollectionService, Depends(get_collection_service)]
EvaluationServiceDep = Annotated[EvaluationService, Depends(get_evaluation_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/collections",
    summary="List the current user's collections, flat across sub-collections unless roots_only",
    response_model=Page[CollectionOut],
)
async def list_collections(
    user: UserDep,
    service: ServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
    roots_only: Annotated[bool, Query()] = False,
) -> Page[CollectionOut]:
    return await service.list_collections(user, pagination, roots_only=roots_only)


@router.post(
    "/collections",
    summary="Create a new, empty collection",
    status_code=status.HTTP_201_CREATED,
    response_model=CollectionOut,
)
async def create_collection(user: UserDep, service: ServiceDep, body: CollectionCreate | None = None) -> CollectionOut:
    try:
        return await service.create_collection(
            user,
            name=body.name if body else None,
            description=body.description if body else None,
            parent_id=body.parent_id if body else None,
        )
    except (HierarchyError, ParentCollectionNotFoundError) as error:
        raise _hierarchy_http_error(error) from error


@router.get(
    "/collections/{collection_id}",
    summary="Get a collection",
    response_model=CollectionOut,
)
async def get_collection(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> CollectionOut:
    try:
        return await service.get_collection(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/children",
    summary="List the direct sub-collections of a collection the user can read",
    response_model=Page[CollectionOut],
)
async def list_children(
    collection_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[CollectionOut]:
    try:
        return await service.list_children(collection_id, user, pagination)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.patch(
    "/collections/{collection_id}",
    summary="Update a collection's name, description and/or tags, or move it (parent_id)",
    response_model=CollectionOut,
)
async def update_collection(
    collection_id: uuid.UUID,
    update: CollectionUpdate,
    user: UserDep,
    service: ServiceDep,
) -> CollectionOut:
    try:
        return await service.update_collection(collection_id, user, update)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except (HierarchyError, ParentCollectionNotFoundError) as error:
        raise _hierarchy_http_error(error) from error


@router.patch(
    "/collections/{collection_id}/settings",
    summary="Update chunking, embedding model, per-step generation models, and pipeline instructions",
    response_model=CollectionOut,
)
async def update_collection_settings(
    collection_id: uuid.UUID,
    update: CollectionSettingsUpdate,
    user: UserDep,
    service: ServiceDep,
) -> CollectionOut:
    try:
        return await service.update_settings(collection_id, user, update)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except InvalidPipelineWindowsError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.post(
    "/collections/{collection_id}/indexing-estimate",
    summary="The same for settings that are typed and not saved yet (nothing is stored)",
    response_model=IndexingEstimateOut,
)
async def post_indexing_estimate(
    collection_id: uuid.UUID,
    request: IndexingEstimateRequest,
    user: UserDep,
    service: ServiceDep,
) -> IndexingEstimateOut:
    try:
        return await service.indexing_estimate(
            collection_id, user, request.pages, request.pipeline_windows, request.chunking_strategy
        )
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except InvalidPipelineWindowsError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error


@router.get(
    "/collections/{collection_id}/indexing-estimate",
    summary="The calls to the language model that indexing a document of that many pages costs, under the "
    "collection's settings",
    response_model=IndexingEstimateOut,
)
async def get_indexing_estimate(
    collection_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    pages: Annotated[int, Query(ge=1, le=100_000)],
) -> IndexingEstimateOut:
    try:
        return await service.indexing_estimate(collection_id, user, pages)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/qa-pairs",
    summary="List a collection's question/answer pairs (generated and manual)",
    response_model=list[QaPairOut],
)
async def list_qa_pairs(
    collection_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    document_id: uuid.UUID | None = None,
) -> list[QaPairOut]:
    try:
        return await service.list_qa_pairs(collection_id, user, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/groundedness",
    summary="Aggregate this collection's grounding verdicts - proportion of runs whose answer "
    "cited it but wasn't fully supported by evidence, plus recent examples",
    response_model=GroundednessStatsOut,
)
async def get_groundedness_stats(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> GroundednessStatsOut:
    try:
        return await service.get_groundedness_stats(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/feedback",
    summary="Aggregate this collection's user feedback - thumbs up/down counts and reason "
    "breakdown across every run that cited it",
    response_model=FeedbackStatsOut,
)
async def get_feedback_stats(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> FeedbackStatsOut:
    try:
        return await service.get_feedback_stats(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.post(
    "/collections/{collection_id}/evaluations",
    summary="Trigger an evaluation run against this collection's QA pairs - promptfoo "
    "replays retrieval and a judge scores each generated answer (runs asynchronously "
    "in a dedicated worker - see #11). Returns 200 instead of 202 when an identical "
    "run already exists: nothing is dispatched then, the response names it",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_evaluation(
    collection_id: uuid.UUID,
    body: EvaluationTriggerRequest,
    user: UserDep,
    service: EvaluationServiceDep,
):
    # The worker resolves its generator model through the same function (its backend_client's
    # get_default_chat_model hits /internal/llm/default-chat-model) - the trigger-time dedup
    # hash must be computed over the models the worker would actually use.
    default_chat_model = await internal_llm._default_chat_model()
    try:
        result = await service.trigger(collection_id, user, body.k, body.validated_only, default_chat_model)
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    if result.skipped:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "skipped",
                "existing_run_id": str(result.skipped_run_id),
                "existing_run_created_at": (
                    result.skipped_run_created_at.isoformat() if result.skipped_run_created_at else None
                ),
            },
        )
    return {"status": "dispatched", "celery_task_id": result.celery_task_id}


@router.get(
    "/collections/{collection_id}/evaluations",
    summary="List this collection's evaluation runs, most recent first, with their score "
    "averages per metric computed from the run's results.json artifact (see #11)",
    response_model=list[EvaluationRunOut],
)
async def list_evaluations(
    collection_id: uuid.UUID, user: UserDep, service: EvaluationServiceDep
) -> list[EvaluationRunOut]:
    try:
        return await service.list_runs(collection_id, user)
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/evaluations/status",
    summary="Whether an evaluation is currently queued or running for this collection - lets "
    "the UI restore its in-progress state after a reload (see #11)",
    response_model=EvaluationStatusOut,
)
async def get_evaluation_status(
    collection_id: uuid.UUID, user: UserDep, service: EvaluationServiceDep
) -> EvaluationStatusOut:
    try:
        return EvaluationStatusOut(running=await service.is_running(collection_id, user))
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/evaluations/{run_id}/results",
    summary="One run's per-pair detail (question, expected and generated answers, retrieved "
    "sources, per-metric scores), normalized from its results.json artifact (see #11)",
    response_model=list[EvaluationResultOut],
)
async def list_evaluation_results(
    collection_id: uuid.UUID, run_id: uuid.UUID, user: UserDep, service: EvaluationServiceDep
) -> list[EvaluationResultOut]:
    try:
        return await service.run_results(collection_id, run_id, user)
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except EvaluationRunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found") from error


@router.get(
    "/collections/{collection_id}/evaluations/{run_id}/report",
    summary="One run's promptfoo HTML report, served through the backend so every access is "
    "re-checked against the user's collection access (see #11)",
    response_class=Response,
)
async def get_evaluation_report(
    collection_id: uuid.UUID,
    run_id: uuid.UUID,
    user: UserDep,
    service: EvaluationServiceDep,
    download: bool = False,
) -> Response:
    try:
        report = await service.run_report(collection_id, run_id, user)
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except EvaluationRunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found") from error
    except EvaluationArtifactNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No report for this evaluation run"
        ) from error
    headers = {"Content-Disposition": 'attachment; filename="evaluation-report.html"'} if download else None
    return Response(content=report, media_type="text/html", headers=headers)


@router.get(
    "/collections/{collection_id}/evaluations/{run_id}/results.json",
    summary="One run's raw promptfoo results.json - the downloadable source of truth for "
    "everything scored in the run (see #11)",
    response_class=Response,
)
async def download_evaluation_results_json(
    collection_id: uuid.UUID, run_id: uuid.UUID, user: UserDep, service: EvaluationServiceDep
) -> Response:
    try:
        data = await service.run_results_json(collection_id, run_id, user)
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except EvaluationRunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found") from error
    except EvaluationArtifactNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No results for this evaluation run"
        ) from error
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="evaluation-results.json"'},
    )


@router.delete(
    "/collections/{collection_id}/evaluations/{run_id}",
    summary="Delete an evaluation run and its RustFS artifacts (see #11)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_evaluation(
    collection_id: uuid.UUID,
    run_id: uuid.UUID,
    user: UserDep,
    service: EvaluationServiceDep,
) -> None:
    try:
        await service.delete_run(collection_id, run_id, user)
    except EvaluationCollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except EvaluationRunNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found") from error


@router.get(
    "/collections/{collection_id}/chunks",
    summary="List a collection's chunks (paginated) - the extracted text segments used for retrieval",
    response_model=Page[ChunkOut],
)
async def list_chunks(
    collection_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[ChunkOut]:
    try:
        return await service.list_chunks(collection_id, user, pagination)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/entities",
    summary="List a collection's extracted entities",
    response_model=list[EntityOut],
)
async def list_entities(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[EntityOut]:
    try:
        return await service.list_entities(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/entities/{entity_id}/mentions",
    summary="Where an entity is in the text (#352): its occurrences - document, page, interval of characters - in "
    "the order one reads them, in one document when `document_id` is given",
    response_model=list[EntityMentionOut],
)
async def list_entity_mentions(
    collection_id: uuid.UUID,
    entity_id: uuid.UUID,
    user: UserDep,
    service: ServiceDep,
    document_id: uuid.UUID | None = None,
) -> list[EntityMentionOut]:
    try:
        return await service.list_entity_mentions(collection_id, user, entity_id, document_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.get(
    "/collections/{collection_id}/relations",
    summary="List a collection's extracted relations between entities",
    response_model=list[RelationOut],
)
async def list_relations(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[RelationOut]:
    try:
        return await service.list_relations(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.delete(
    "/collections/{collection_id}",
    summary="Delete a collection",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_collection(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_collection(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.patch(
    "/collections/{collection_id}/visibility",
    summary="Make a collection private (default) or public - owner only",
    response_model=CollectionOut,
)
async def update_visibility(
    collection_id: uuid.UUID,
    update: VisibilityUpdate,
    user: UserDep,
    service: ServiceDep,
) -> CollectionOut:
    try:
        return await service.update_visibility(collection_id, user, update.visibility)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.post(
    "/collections/{collection_id}/shares",
    summary="Invite a user (by email) or a Keycloak group to a collection - owner only. Never "
    "confirms whether the identifier matches a real account/group: it's always created PENDING "
    "and resolved the next time a matching user logs in (see app/core/sharing.py).",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareOut,
)
async def create_share(collection_id: uuid.UUID, create: ShareCreate, user: UserDep, service: ServiceDep) -> ShareOut:
    try:
        return await service.create_share(collection_id, user, create)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except AlreadyInvitedError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already invited") from error
    except SharingNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sharing is not configured",
        ) from error


@router.get(
    "/collections/{collection_id}/shares",
    summary="List a collection's pending and active shares - owner only",
    response_model=list[ShareOut],
)
async def list_shares(collection_id: uuid.UUID, user: UserDep, service: ServiceDep) -> list[ShareOut]:
    try:
        return await service.list_shares(collection_id, user)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.delete(
    "/collections/{collection_id}/shares/{share_id}",
    summary="Revoke a pending or active share - owner only",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_share(collection_id: uuid.UUID, share_id: uuid.UUID, user: UserDep, service: ServiceDep) -> None:
    try:
        await service.delete_share(collection_id, user, share_id)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error
    except ShareNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found") from error
