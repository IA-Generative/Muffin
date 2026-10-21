import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PipelineStage(enum.StrEnum):
    """What the document pipeline derives from a file, each with its own settings (#300): a stage is
    reused from another document of the same file when its fingerprint matches, whatever the others'."""

    EXTRACTION = "extraction"  # the pages and their screenshots
    CHUNKS = "chunks"  # the chunks and their vectors
    SUMMARY = "summary"  # the summary, and its vector
    QA = "qa"  # the generated question/answer pairs, and their vectors
    ENTITIES = "entities"  # the entities and relations
    TAGS = "tags"  # the document's tags


class DocumentStage(Base):
    """One stage of the pipeline as it ran for a document (#300): the fingerprint of the file and of
    the settings that stage depends on, and whether it is complete. Another document of the same file
    reuses a complete stage of equal fingerprint instead of computing it again - the OCR, the embeddings
    and the LLM calls are what it saves. Internal: never shown to a user, who must not learn which other
    collection a result came from."""

    __tablename__ = "document_stages"
    __table_args__ = (
        # The lookup of a source: a complete stage of this fingerprint.
        Index("ix_document_stages_lookup", "stage", "fingerprint", postgresql_where=text("completed_at IS NOT NULL")),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[str] = mapped_column(String, primary_key=True)
    # Opaque to the backend: the worker computes it, from the file's hash and the settings of the stage.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # A stage run in pieces (the QA pairs of each window of pages) is complete once every piece it
    # announced is done; one with a single piece announces none.
    expected: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    done: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # The document this stage was copied from, when it was not computed: for the logs and for tracing a
    # bad copy. SET NULL: the copy stands on its own once its source is deleted.
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def to_json(self) -> dict[str, Any]:
        return {"stage": self.stage, "fingerprint": self.fingerprint, "complete": self.completed_at is not None}
