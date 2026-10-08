"""The edit job's input/output contract (#167). The backend builds the input and reads the result
back; neither side shares code with the other (same convention as the other workers), so this
file and backend/app/core/tasks.py are the two places to keep in agreement."""

from typing import Literal

from pydantic import BaseModel, Field


class EditJobInput(BaseModel):
    # The living document's current file, as stored in RustFS (Document.storage_key).
    source_storage_key: str
    # The user's instruction, plus whatever chat context the research agent judged useful.
    prompt: str = Field(min_length=1)
    document_id: str
    # Revision the edit is based on - echoed back so the backend can refuse to promote the draft
    # if the document moved on in the meantime (#170).
    base_revision: int = Field(ge=1)
    format: Literal["odt", "md"]
    run_id: str | None = None
    user_id: str
    # Set when the user asked for an adjustment of an earlier draft rather than a fresh edit: the
    # job then starts from that draft instead of from source_storage_key.
    previous_draft_key: str | None = None


class PendingImage(BaseModel):
    """A spot where an image would help - the agent never generates or fetches one, the user
    uploads it while validating the draft (#169)."""

    id: str
    description: str


class EditJobResult(BaseModel):
    # RustFS key of the edited copy. The source file is never modified.
    draft_storage_key: str
    # RustFS key of the PDF preview shown to the user - None until the conversion is wired (#169).
    preview_pdf_key: str | None = None
    # Human-readable list of the operations applied, shown next to the preview.
    operations_summary: str = ""
    pending_images: list[PendingImage] = []
    # False while the worker only copies its starting point unchanged (this skeleton, #167).
    edited: bool = False
