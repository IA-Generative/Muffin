import uuid

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    status: str
    progress: int


class DocumentDetailOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    status: str
    progress: int
    summary: str | None
    error: str | None
    tags: list[str]
    page_count: int


class DocumentPageOut(BaseModel):
    page_number: int
    content: str
    screenshot_url: str | None


class DocumentUrlCreate(BaseModel):
    url: str
