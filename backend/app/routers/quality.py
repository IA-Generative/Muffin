"""Quality dashboard router (see #33).

Cross-collection aggregation of quality metrics:
- GET  /api/quality/overview          — all families aggregated (admin: all, user: own)
- GET  /api/quality/overview?collection_id=...  — scoped to one collection
- POST /api/quality/conversations/{id}/score  — trigger LLM discussion scoring
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.quality import QualityOverviewOut
from app.services.quality_service import (
    ConversationNotFoundError,
    QualityService,
)

router = APIRouter(tags=["Quality"])


def get_quality_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QualityService:
    return QualityService(db)


QualityServiceDep = Annotated[QualityService, Depends(get_quality_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/quality/overview",
    summary="Cross-collection quality metrics: retrieval, feedback, discussion, groundedness (see #33)",
    response_model=QualityOverviewOut,
)
async def get_quality_overview(
    user: UserDep,
    service: QualityServiceDep,
    collection_id: Annotated[uuid.UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    model_filter: Annotated[str | None, Query()] = None,
) -> QualityOverviewOut:
    from app.services.quality_service import CollectionNotFoundError

    try:
        return await service.get_overview(user, collection_id, page, page_size, model_filter)
    except CollectionNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found") from error


@router.post(
    "/quality/conversations/{conversation_id}/score",
    summary="Trigger an LLM discussion-quality judgment for this conversation (see #31)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_discussion_score(
    conversation_id: uuid.UUID,
    user: UserDep,
    service: QualityServiceDep,
    model: Annotated[str | None, Query()] = None,
) -> dict[str, str]:
    try:
        celery_task_id = await service.trigger_discussion_score(conversation_id, user, model)
    except ConversationNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found") from error
    return {"celery_task_id": celery_task_id}


@router.post(
    "/quality/conversations/score-all",
    summary="Trigger LLM discussion scoring for all unscored conversations (see #33)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_score_all(
    user: UserDep,
    service: QualityServiceDep,
    collection_id: Annotated[uuid.UUID | None, Query()] = None,
    model: Annotated[str | None, Query()] = None,
) -> dict[str, list[str] | int]:
    celery_task_ids = await service.trigger_score_all(user, collection_id, model)
    return {"celery_task_ids": celery_task_ids, "count": len(celery_task_ids)}
