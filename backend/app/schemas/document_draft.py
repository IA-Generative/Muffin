import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.document_draft import DocumentDraft


class DraftCreate(BaseModel):
    """What the user asks for - on creation and on every adjustment."""

    prompt: str = Field(min_length=1, max_length=4000)

    @field_validator("prompt")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class DraftImageOut(BaseModel):
    id: str
    description: str
    section: dict[str, Any] | None
    after_paragraph: int | None
    # A file was uploaded for this spot but isn't in the draft yet.
    uploaded: bool
    # It is in the draft now.
    inserted: bool


class DraftOut(BaseModel):
    id: uuid.UUID
    status: str
    # "edit" or "images": which job is running, or ran last.
    job_kind: str
    prompt: str
    base_revision: int
    format: str
    # False: the agent changed nothing - operations_summary is its explanation, nothing to validate.
    edited: bool
    operations_summary: str
    error: str | None
    # What GET .../draft/preview serves: the PDF of an edited ODT, the text of an edited Markdown.
    preview: Literal["pdf", "markdown"] | None
    pending_images: list[DraftImageOut]
    # When the draft (and the document lock it holds) lapses unless it is used again.
    expires_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, draft: DocumentDraft, expires_at: datetime | None) -> "DraftOut":
        if draft.preview_pdf_key:
            preview = "pdf"
        elif draft.format == "md" and draft.edited and draft.draft_storage_key:
            preview = "markdown"
        else:
            preview = None
        return cls(
            id=draft.id,
            status=draft.status,
            job_kind=draft.job_kind,
            prompt=draft.prompt,
            base_revision=draft.base_revision,
            format=draft.format,
            edited=draft.edited,
            operations_summary=draft.operations_summary,
            error=draft.error,
            preview=preview,
            pending_images=[
                DraftImageOut(
                    id=image["id"],
                    description=image["description"],
                    section=image.get("section"),
                    after_paragraph=image.get("after_paragraph"),
                    uploaded=bool(image.get("storage_key")) and not image.get("inserted"),
                    inserted=bool(image.get("inserted")),
                )
                for image in draft.pending_images
            ],
            expires_at=expires_at,
            created_at=draft.created_at,
        )


# -- what the worker reports back (internal) -----------------------------------------------------


class PendingImageIn(BaseModel):
    id: str
    description: str
    section: dict[str, Any] | None = None
    after_paragraph: int | None = None


class DraftResultIn(BaseModel):
    """worker/document_edit's EditJobResult plus which job produced it."""

    kind: Literal["edit", "images"]
    draft_storage_key: str
    preview_pdf_key: str | None = None
    operations_summary: str = ""
    pending_images: list[PendingImageIn] = []
    edited: bool = False


class DraftFailureIn(BaseModel):
    error: str
