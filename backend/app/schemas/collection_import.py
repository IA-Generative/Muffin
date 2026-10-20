import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models.collection_import import CollectionImportStatus


class CollectionImportOut(BaseModel):
    """A ZIP import (#223) as its owner sees it - polled until `status` is terminal."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: CollectionImportStatus
    archive_name: str
    # Created when the archive is uploaded, so it can be opened right away - NULL only if it has
    # been deleted since.
    root_collection_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    # {"collections_created", "documents_created", "skipped": [{"path", "reason"}]} once done.
    summary: dict[str, Any] | None
    error: str | None
    created_at: datetime


class CollectionImportInternalOut(BaseModel):
    """What worker/document_process's import_zip needs to run an import."""

    id: uuid.UUID
    archive_key: str | None
    root_collection_id: uuid.UUID | None


class ImportedCollectionCreate(BaseModel):
    parent_id: uuid.UUID
    name: str


class ImportedCollectionOut(BaseModel):
    id: uuid.UUID


class ImportedDocumentCreate(BaseModel):
    collection_id: uuid.UUID
    name: str
    # Already stored by the worker, under documents/<collection_id>/ - checked backend-side.
    storage_key: str


class CollectionImportResult(BaseModel):
    status: Literal["completed", "failed"]
    summary: dict[str, Any] | None = None
    error: str | None = None
