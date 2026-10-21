import uuid

from pydantic import BaseModel


class QaSuggestionOut(BaseModel):
    """A question offered on an empty chat (#126): clicking it shows the pair's answer and source
    straight away."""

    id: uuid.UUID
    question: str
    collection_id: uuid.UUID
    collection_name: str


class QaAnswerRequest(BaseModel):
    # Into an existing conversation of the caller's, or - without one - into a new conversation.
    conversation_id: uuid.UUID | None = None


class QaAnswerOut(BaseModel):
    conversation_id: uuid.UUID
    run_id: uuid.UUID
