import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ShareSubjectType(enum.StrEnum):
    USER = "user"
    GROUP = "group"


class ChunkingStrategy(enum.StrEnum):
    PARAGRAPH = "paragraph"
    FIXED = "fixed"
    SEMANTIC = "semantic"
    LLM = "llm"


class Collection(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "collections"

    # Keycloak subject (sub) claim; a collection always has exactly one owner.
    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    description_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags_updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    tags_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tags: Mapped[list["CollectionTag"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    shares: Mapped[list["CollectionShare"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    settings: Mapped["CollectionSettings"] = relationship(
        back_populates="collection", cascade="all, delete-orphan", uselist=False
    )
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )
    qa_pairs: Mapped[list["QaPair"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )
    entities: Mapped[list["Entity"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )
    relations: Mapped[list["Relation"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )
    evaluation_runs: Mapped[list["EvaluationRun"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )


class CollectionTag(Base):
    __tablename__ = "collection_tags"

    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True)

    collection: Mapped["Collection"] = relationship(back_populates="tags")


class CollectionShare(UUIDMixin, TimestampMixin, Base):
    """A collection shared with a person or a group (Keycloak user sub or group id)."""

    __tablename__ = "collection_shares"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_type: Mapped[ShareSubjectType] = mapped_column(
        Enum(ShareSubjectType, name="share_subject_type"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String, nullable=False)

    collection: Mapped["Collection"] = relationship(back_populates="shares")


class CollectionSettings(Base):
    """One-to-one: chunking/embedding parameters and pipeline instructions for a collection."""

    __tablename__ = "collection_settings"

    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    chunking_strategy: Mapped[ChunkingStrategy] = mapped_column(
        Enum(ChunkingStrategy, name="chunking_strategy"),
        nullable=False,
        default=ChunkingStrategy.PARAGRAPH,
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    reindex_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    instructions_qa: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions_extraction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions_chunking: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions_tagging: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Chat model used for each generation step - {"qa": "...", "extraction":
    # "...", "chunking": "...", "tagging": "...", "summary": "..."}. Each key
    # is None until the user picks one; the caller (worker task) defaults to
    # the first model GET /api/models returns rather than hardcoding one here.
    generation_models: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Sliding-window params for the steps that read several pages of a
    # document at once instead of one chunk at a time - summary (map-reduce),
    # QA generation, entity/relation extraction, and semantic chunking. Flat
    # dict (not nested per step) so a partial update can merge by top-level
    # key the same way generation_models does; missing keys fall back to
    # PipelineWindowsOut's defaults, see app/schemas/collection.py.
    pipeline_windows: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    collection: Mapped["Collection"] = relationship(back_populates="settings")
