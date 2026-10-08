import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    # "standard" or "living" (#166) - a living document has a revision history.
    kind: str = "standard"
    status: str
    progress: int
    # Filing suggestion (§122) - all None for a document created before this existed, or one
    # that was never uploaded straight into a conversation (a regular collection upload has no
    # temporary-collection detour to suggest filing out of in the first place).
    added_by_display: str | None = None
    suggested_collection_id: uuid.UUID | None = None
    suggested_collection_name: str | None = None
    suggested_collection_score: float | None = None
    # Top-K behind suggested_collection_id/score (which is just candidates[0]) - a point-in-time
    # snapshot (collection_id/name/description/score), see Document.filing_candidates.
    filing_candidates: list[dict[str, Any]] | None = None
    filing_dismissed: bool = False


class DocumentLockOut(BaseModel):
    """Who is editing a living document and until when (#170) - never carries the token, which
    only the holder gets (see DocumentLockGrantOut)."""

    locked_by_display: str | None
    expires_at: datetime
    # True when the lock belongs to the calling user - e.g. their own session in another tab.
    held_by_me: bool

    @classmethod
    def from_document(cls, document: Any, user_id: str, now: datetime) -> "DocumentLockOut | None":
        if document.lock_expires_at is None or document.lock_expires_at <= now:
            return None
        return cls(
            locked_by_display=document.locked_by_display,
            expires_at=document.lock_expires_at,
            held_by_me=document.locked_by_user_id == user_id,
        )


class DocumentLockGrantOut(DocumentLockOut):
    token: str


class DocumentDetailOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    kind: str = "standard"
    # Number of the current revision - None for a standard document.
    current_revision: int | None = None
    lock: DocumentLockOut | None = None
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


class FilingCandidateOut(BaseModel):
    """A document its uploader still hasn't filed into a permanent collection they control
    (§122) - the "Fichiers à ranger" review page's row shape. Not DocumentOut: this needs the
    *current* collection's own name/editability, which DocumentOut (used for an ordinary
    collection's document list, where that's always implicitly "yes, this very collection") has
    no reason to carry."""

    id: uuid.UUID
    name: str
    added_by_display: str | None
    collection_id: uuid.UUID
    collection_name: str
    collection_is_temporary: bool
    collection_editable: bool
    suggested_collection_id: uuid.UUID | None
    suggested_collection_name: str | None
    suggested_collection_score: float | None
    filing_candidates: list[dict[str, Any]] | None
    filing_dismissed: bool
    created_at: datetime


class FilingDecision(BaseModel):
    action: str  # "accept" | "choose_other" | "dismiss"
    target_collection_id: uuid.UUID | None = None


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


class DocumentRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    filename: str
    format: str
    origin: str
    created_by_display: str | None
    restored_from_number: int | None
    created_at: datetime
    is_current: bool = False
