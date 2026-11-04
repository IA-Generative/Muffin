from enum import StrEnum

from pydantic import BaseModel, Field

# The value of a run's model that lets the agent choose it.
AUTO_MODEL = "auto"


class ModelCapability(StrEnum):
    """What a model can do, worked out by the backend and shown as tags: an administrator describes how *good* a model
    is, never what it *is*."""

    CHAT = "chat"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    IMAGE_GENERATION = "image_generation"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"


class ModelProfileUpdate(BaseModel):
    score: int = Field(ge=0, le=100)
    description: str | None = Field(default=None, max_length=1000)
    auto_enabled: bool = True


class ModelProfileOut(BaseModel):
    id: str
    capabilities: list[ModelCapability]
    score: int
    description: str | None
    auto_enabled: bool
    # False while no administrator has described the model: it then carries the default score.
    described: bool


class ModelProfilesOut(BaseModel):
    models: list[ModelProfileOut]
    # The model that classifies the requests, if one was chosen; None: the cheapest one the automatic choice may pick.
    classifier_model: str | None


class ClassifierModelUpdate(BaseModel):
    classifier_model: str | None = Field(default=None, max_length=200)


class AutoCandidate(BaseModel):
    model: str
    score: int
    description: str | None
    vision: bool


class AutoCandidatesOut(BaseModel):
    """What the agent chooses from in auto mode (internal route): chat models the administrator lets it pick."""

    candidates: list[AutoCandidate]
    classifier_model: str | None
