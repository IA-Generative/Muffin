import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from app.models.collection_import import CollectionImportStatus

if TYPE_CHECKING:
    from app.models.collection import Collection as CollectionModel
    from app.models.collection_import import CollectionImport as CollectionImportModel


class AttachCandidateOut(BaseModel):
    collection_id: uuid.UUID
    collection_name: str
    # The "why" shown to the user, as for a filing suggestion (§122): the candidate's own
    # description, no generated explanation.
    collection_description: str
    score: float


# not_applicable: dropped into a collection, it's already where the user put it. pending: waiting
# for the user's answer - `attach_candidates` stays empty until the collection has a description to
# compare. attached: it now sits under another collection. dismissed: the user said no.
AttachStatus = Literal["not_applicable", "pending", "attached", "dismissed"]


class CollectionImportOut(BaseModel):
    """A ZIP import (#223) as its owner sees it - polled until `status` is terminal."""

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
    root_collection_name: str | None = None
    attach_status: AttachStatus = "not_applicable"
    # Best first - the suggestion is the first one.
    attach_candidates: list[AttachCandidateOut] = []

    @classmethod
    def from_model(
        cls, collection_import: "CollectionImportModel", root: "CollectionModel | None"
    ) -> "CollectionImportOut":
        if not collection_import.attach_eligible or root is None:
            attach_status: AttachStatus = "not_applicable"
        elif root.parent_id is not None:
            attach_status = "attached"
        elif collection_import.attach_dismissed:
            attach_status = "dismissed"
        else:
            attach_status = "pending"
        return cls(
            id=collection_import.id,
            status=collection_import.status,
            archive_name=collection_import.archive_name,
            root_collection_id=collection_import.root_collection_id,
            conversation_id=collection_import.conversation_id,
            summary=collection_import.summary,
            error=collection_import.error,
            created_at=collection_import.created_at,
            root_collection_name=root.name if root is not None else None,
            attach_status=attach_status,
            attach_candidates=[
                AttachCandidateOut(**candidate) for candidate in collection_import.attach_candidates or []
            ],
        )


class AttachDecision(BaseModel):
    action: Literal["accept", "choose_other", "dismiss"]
    target_collection_id: uuid.UUID | None = None


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
