import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: int
    content: str
    is_active: bool
    created_at: datetime


class PromptSummaryOut(BaseModel):
    name: str
    active_version: PromptVersionOut | None


class PromptVersionCreate(BaseModel):
    content: str


class ActivePromptOut(BaseModel):
    """Worker-facing shape (see internal_prompts.py) - just enough to run the LLM call and
    record which version produced the answer, nothing admin-only like history/is_active."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: int
    content: str


class RunPromptUsagesCreate(BaseModel):
    prompt_version_ids: list[uuid.UUID]
