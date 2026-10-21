"""The edit job's input/output contract (#167). The backend builds the input and reads the result
back; neither side shares code with the other (same convention as the other workers), so this
file and backend/app/core/tasks.py are the two places to keep in agreement."""

from typing import Literal

from pydantic import BaseModel, Field

from app.operations import SectionRef


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
    # Also render the PDF of the source file (ODT only), so the user can look at the current document
    # next to the proposal. Set on a draft's first job only: an adjustment finds it already there.
    render_base: bool = False


class PendingImage(BaseModel):
    """A spot where an image would help - the agent never generates or fetches one, the user
    uploads it while validating the draft (#169)."""

    id: str
    description: str
    # Where it would go - same convention as an operation's target; both None means "at the end of
    # the document". The user places the actual image while validating the draft.
    section: SectionRef | None = None
    after_paragraph: int | None = Field(default=None, ge=0)


class EditJobResult(BaseModel):
    # RustFS key of the edited copy. The source file is never modified.
    draft_storage_key: str
    # RustFS key of the PDF preview shown to the user - None until the conversion is wired (#169).
    preview_pdf_key: str | None = None
    # RustFS key of the PDF of the document the draft started from - only when the job rendered it.
    base_preview_pdf_key: str | None = None
    # Human-readable list of the operations applied, shown next to the preview.
    operations_summary: str = ""
    pending_images: list[PendingImage] = []
    # False while the worker only copies its starting point unchanged (this skeleton, #167).
    edited: bool = False


class RenderUploadInput(BaseModel):
    """Input of the render_upload task: the PDF previews of a file the user picked to replace an ODT
    document - the file itself and the document it would replace - so they can be compared before
    anything is saved. No model involved."""

    # The picked file, already in RustFS (under drafts/): the result points back at it, unchanged.
    draft_storage_key: str
    # The document's current file.
    source_storage_key: str
    document_id: str
    user_id: str


class ImageToInsert(BaseModel):
    """An image the user uploaded for one of a draft's pending spots (#169)."""

    id: str
    description: str
    # RustFS key of the uploaded file.
    storage_key: str
    section: SectionRef | None = None
    after_paragraph: int | None = Field(default=None, ge=0)


class InsertImagesInput(BaseModel):
    """Input of the insert_images task: put uploaded images into an existing ODT draft and render
    a fresh preview. No model involved - a deterministic step."""

    # The draft to add the images to (its latest file).
    draft_storage_key: str
    document_id: str
    images: list[ImageToInsert] = Field(min_length=1)
    user_id: str
