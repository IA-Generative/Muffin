import uuid
from typing import Any

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


class TabularProfileOut(BaseModel):
    """Profil statistique d'un document tabulaire, exposé au frontend
    pour afficher le schéma, les stats, la classification et un échantillon
    de lignes."""

    model_config = ConfigDict(from_attributes=True)

    row_count: int
    column_count: int
    format: str
    columns: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]
    measures: list[str]
    dimensions: list[str]
    text_columns: list[str]
