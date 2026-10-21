import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.factory import RequestContext, get_current_user
from app.db import get_db
from app.schemas.qa_suggestion import QaAnswerOut, QaAnswerRequest, QaSuggestionOut
from app.services.conversation_service import ConversationNotFoundError
from app.services.qa_suggestion_service import QaPairNotSuggestibleError, QaSuggestionService

router = APIRouter(tags=["Conversations"])


def get_qa_suggestion_service(db: Annotated[AsyncSession, Depends(get_db)]) -> QaSuggestionService:
    return QaSuggestionService(db)


ServiceDep = Annotated[QaSuggestionService, Depends(get_qa_suggestion_service)]
UserDep = Annotated[RequestContext, Depends(get_current_user)]


@router.get(
    "/qa-suggestions",
    summary="A few questions to start a chat with, drawn at random from the question/answer pairs of the "
    "collections the caller can read (reviewed pairs first; only those pinned when collection_ids is given)",
    response_model=list[QaSuggestionOut],
)
async def list_suggestions(
    user: UserDep,
    service: ServiceDep,
    collection_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> list[QaSuggestionOut]:
    return await service.suggest(user, collection_ids)


@router.post(
    "/qa-suggestions/{qa_pair_id}/answer",
    summary="Ask a suggested question: the conversation gets the pair's stored answer and its source, "
    "without running the research agent",
    response_model=QaAnswerOut,
    status_code=status.HTTP_201_CREATED,
)
async def answer_suggestion(
    qa_pair_id: uuid.UUID, body: QaAnswerRequest, user: UserDep, service: ServiceDep
) -> QaAnswerOut:
    try:
        return await service.answer(user, qa_pair_id, body.conversation_id)
    except QaPairNotSuggestibleError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found") from error
    except ConversationNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found") from error
