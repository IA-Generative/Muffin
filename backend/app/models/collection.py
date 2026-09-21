import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ShareSubjectType(enum.StrEnum):
    USER = "user"
    GROUP = "group"


class ShareStatus(enum.StrEnum):
    # Created from an email/group identifier the backend never confirmed against Keycloak (no
    # live lookup - see app/core/sharing.py) - resolved to ACTIVE the next time a matching
    # user logs in, never by anything the owner who created it can observe.
    PENDING = "pending"
    ACTIVE = "active"


class CollectionVisibility(enum.StrEnum):
    PRIVATE = "private"
    PUBLIC = "public"


class ChunkingStrategy(enum.StrEnum):
    PARAGRAPH = "paragraph"
    FIXED = "fixed"
    SEMANTIC = "semantic"
    LLM = "llm"


class Collection(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "collections"

    # Keycloak subject (sub) claim; a collection always has exactly one owner.
    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    visibility: Mapped[CollectionVisibility] = mapped_column(
        Enum(CollectionVisibility, name="collection_visibility"),
        nullable=False,
        default=CollectionVisibility.PRIVATE,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    description_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags_updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    tags_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Temporary collections (§ conv-files) are auto-created lazily on the first file uploaded
    # directly into a conversation (never by the user explicitly) - excluded from the normal
    # collections list and auto-pinned to that conversation's runs instead. is_temporary is
    # redundant with conversation_id being non-NULL, but kept as its own column: filtering
    # `WHERE is_temporary` reads clearer than `WHERE conversation_id IS NOT NULL` at call sites,
    # and it's the one invariant this model can enforce in Python if the two ever needed to
    # diverge (they don't today).
    is_temporary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, unique=True
    )

    tags: Mapped[list["CollectionTag"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    shares: Mapped[list["CollectionShare"]] = relationship(back_populates="collection", cascade="all, delete-orphan")
    settings: Mapped["CollectionSettings"] = relationship(
        back_populates="collection", cascade="all, delete-orphan", uselist=False
    )
    description_embedding: Mapped["CollectionDescriptionEmbedding | None"] = relationship(
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
    conversation: Mapped["Conversation | None"] = relationship(  # noqa: F821
        back_populates="temporary_collection", foreign_keys=[conversation_id]
    )


class CollectionTag(Base):
    __tablename__ = "collection_tags"

    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    tag: Mapped[str] = mapped_column(String, primary_key=True)

    collection: Mapped["Collection"] = relationship(back_populates="tags")


class CollectionShare(UUIDMixin, TimestampMixin, Base):
    """A collection shared with a person or a group (Keycloak user sub or group id).

    Created PENDING from an email/group identifier the backend never looked up against Keycloak
    (see app/core/sharing.py) - only invited_identifier_hash is set, subject_id is NULL. Promoted
    to ACTIVE (subject_id filled with the Keycloak sub/group id, invited_identifier_hash cleared)
    the next time a user whose token claims hash to the same value logs in."""

    __tablename__ = "collection_shares"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_type: Mapped[ShareSubjectType] = mapped_column(
        Enum(ShareSubjectType, name="share_subject_type"), nullable=False
    )
    status: Mapped[ShareStatus] = mapped_column(
        Enum(ShareStatus, name="share_status"), nullable=False, default=ShareStatus.PENDING, index=True
    )
    # Keycloak sub (subject_type=user) or group id/path (subject_type=group) - NULL until resolved.
    subject_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # HMAC-SHA256 of the normalized email/group identifier the owner typed - NULL once ACTIVE.
    invited_identifier_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Non-reversible display hint (e.g. "j***@e***.com") computed once at creation time from what
    # the owner just typed in that same request - never reconstituted from the hash afterwards.
    display_hint: Mapped[str] = mapped_column(String, nullable=False)

    collection: Mapped["Collection"] = relationship(back_populates="shares")

    __table_args__ = (
        # Prevents a second pending invitation for the same not-yet-resolved identifier. NULLs
        # (every ACTIVE row, once invited_identifier_hash is cleared) are never considered equal
        # to each other by Postgres, so this only ever constrains PENDING rows against each other.
        UniqueConstraint(
            "collection_id", "subject_type", "invited_identifier_hash", name="uq_collection_share_pending_identifier"
        ),
        # Prevents a duplicate ACTIVE share once resolved. Same NULL-distinct reasoning lets many
        # PENDING rows (subject_id NULL) coexist without tripping this one.
        UniqueConstraint("collection_id", "subject_type", "subject_id", name="uq_collection_share_active_subject"),
    )


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


class CollectionDescriptionEmbedding(Base):
    """One-to-one, kept out of the `collections` table itself (it's large
    and rewritten on every description change, unlike the rest of that row).
    Always computed with the LLM hub's default embedding model - global
    across every collection, not user-configurable, because comparing a
    query's embedding against collections to pick the right one only works
    if they all live in the same embedding space."""

    __tablename__ = "collection_description_embeddings"

    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False)

    collection: Mapped["Collection"] = relationship(back_populates="description_embedding")
