import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportDocument(Base):
    """A document an import created, and where it is in the import's window of extractions (#335). Its
    processing is not queued when it is registered - an archive of 2000 files would put them all in the
    queue - but when the import has room: at most IMPORT_PROCESSING_WINDOW of its documents are being
    extracted at a time, and the end of one releases the next."""

    __tablename__ = "import_documents"
    __table_args__ = (Index("ix_import_documents_waiting", "import_id", "created_at", "document_id"),)

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collection_imports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # When its processing was queued - None while it waits for its turn.
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When its extraction ended (the chunking took over) - None until then. What frees its place.
    extraction_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
