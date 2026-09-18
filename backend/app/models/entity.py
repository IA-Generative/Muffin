import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class EntityType(enum.StrEnum):
    PERSONNE = "personne"
    ORGANISATION = "organisation"
    LIEU = "lieu"
    DATE = "date"
    AUTRE = "autre"


class Entity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "entities"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[EntityType] = mapped_column(Enum(EntityType, name="entity_type"), nullable=False)
    # Collection-wide running total (the same "Jean Dupont" mentioned in several documents of
    # this collection is one Entity row, not one per document - see EntityDocument below for the
    # per-document breakdown of that same count).
    mentions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    collection: Mapped["Collection"] = relationship(back_populates="entities")  # noqa: F821


class EntityDocument(Base):
    """Which documents an entity was actually mentioned in, and how many times in each - Entity
    itself stays collection-scoped (its cross-document merge/mentions-count behavior is
    unchanged), this is purely an additive per-document breakdown for document-scoped views
    (e.g. the document detail modal) that a plain document_id column on Entity couldn't give
    without breaking that merge."""

    __tablename__ = "entity_documents"

    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    mentions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Relation(UUIDMixin, Base):
    __tablename__ = "relations"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Nullable: a relation is always extracted from one specific document's text window, but
    # existing rows created before this column existed have no way to know which - null there
    # just means "not shown in a document-scoped view", the collection-wide one is unaffected.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)

    collection: Mapped["Collection"] = relationship(back_populates="relations")  # noqa: F821
    from_entity: Mapped["Entity"] = relationship(foreign_keys=[from_entity_id])
    to_entity: Mapped["Entity"] = relationship(foreign_keys=[to_entity_id])
