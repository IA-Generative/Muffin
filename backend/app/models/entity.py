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
    mentions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    collection: Mapped["Collection"] = relationship(back_populates="entities")  # noqa: F821


class Relation(UUIDMixin, Base):
    __tablename__ = "relations"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)

    collection: Mapped["Collection"] = relationship(back_populates="relations")  # noqa: F821
    from_entity: Mapped["Entity"] = relationship(foreign_keys=[from_entity_id])
    to_entity: Mapped["Entity"] = relationship(foreign_keys=[to_entity_id])
