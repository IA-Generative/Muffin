import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin


class Chunk(UUIDMixin, Base):
    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # liteparse layout data for this chunk - bbox, block kind, etc. Absent for
    # chunks that don't come from a spatial parse (e.g. scraped URL markdown).
    extras: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="chunks")  # noqa: F821
