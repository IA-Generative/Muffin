import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class DraftStatus(enum.StrEnum):
    # A worker job (an edit, or the insertion of uploaded images) is running.
    PENDING = "pending"
    # The draft is there to look at: validate, adjust or refuse it.
    READY = "ready"
    # The edit job failed - `error` says why. The user can adjust (retry) or refuse.
    FAILED = "failed"


class DocumentDraft(UUIDMixin, TimestampMixin, Base):
    """An edit of a living document waiting for the user's verdict (#169). One at most per
    document: it holds the document's edit lock for as long as it lives, so nobody else can change
    the document underneath it, and it disappears - files included - when validated, refused or
    when that lock lapses (an abandoned draft). Nothing here is ever indexed or cited: only a
    validated draft, promoted to a revision, becomes part of the collection."""

    __tablename__ = "document_drafts"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    # The revision the edit started from - validating is refused if the document moved on (#170).
    base_revision: Mapped[int] = mapped_column(nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus, name="draft_status"), nullable=False)
    # What the running (or last) job is: "edit" or "images".
    job_kind: Mapped[str] = mapped_column(String, nullable=False, default="edit")
    # The user's latest instruction (the one that produced - or is producing - the current draft).
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(String, nullable=False)
    requested_by_display: Mapped[str | None] = mapped_column(String, nullable=True)
    # The Celery task of the running (or last) job - how the worker's report finds its draft.
    celery_task_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    # The token of the document lock this draft holds on the user's behalf - kept server-side, the
    # client never needs it: every action on the draft goes through here.
    lock_token: Mapped[str] = mapped_column(String, nullable=False)

    draft_storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    preview_pdf_key: Mapped[str | None] = mapped_column(String, nullable=True)
    operations_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # False when the agent found nothing to change (or declined): operations_summary is then its
    # explanation, and there is nothing to validate.
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Spots where the agent thinks an image belongs, and what the user uploaded for them:
    # [{"id", "description", "section", "after_paragraph", "storage_key", "content_type",
    # "inserted"}]. The agent never produces an image itself.
    pending_images: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
