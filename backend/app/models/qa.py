import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Text
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

    collection: Mapped["Collection"] = relationship(back_populates="qa_pairs")  # noqa: F821
    document: Mapped["Document | None"] = relationship()  # noqa: F821
