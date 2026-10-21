import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class QaOrigin(enum.StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"


class QaPair(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "qa_pairs"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Nullable: a manually created QA pair may not originate from a specific document.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[QaOrigin] = mapped_column(Enum(QaOrigin, name="qa_origin"), nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A "golden" pair is a test question: written by a person, never embedded in the retriever
    # (so no search can match it to itself, and the agent never answers from it), and only ever used
    # to measure - its evaluation scores are reported apart from the generated pairs' (#260). Always
    # validated, since a person wrote it.
    golden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Every document that holds the answer, as ids (strings) - only set on a golden pair, whose
    # answer can span several documents. `document_id` stays the main one (the first), which is what
    # the rest of the code reads; the evaluation counts a retrieved chunk as relevant when its
    # document is in this list.
    relevant_document_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    collection: Mapped["Collection"] = relationship(back_populates="qa_pairs")  # noqa: F821
    document: Mapped["Document | None"] = relationship()  # noqa: F821
