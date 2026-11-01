import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.collection import CollectionVisibility, SharePermission, ShareStatus, ShareSubjectType


class Assistant(UUIDMixin, TimestampMixin, Base):
    """A named setting the chat is started with (#514): collections, instructions for the answer, suggested questions.

    It never grants access to anything: it *designates* collections, and a run searches those among them that the
    person using it may read (AssistantService.resolve). Every change raises `version`, which a run keeps."""

    __tablename__ = "assistants"

    # Keycloak subject of the author.
    owner_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # A short sign to recognise it by (an emoji), and a colour name of the design system.
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # Added to the rules of the answer, never in their place (see generate_answer).
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Whether those who only read the assistant are shown its instructions; they apply either way.
    hide_instructions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Plain ids, with no foreign key: a collection that is deleted leaves the assistant working with the others.
    collection_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    include_descendants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Whether the web search may be turned on in a chat with this assistant. Never on by itself.
    web_search_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Optional tools of the agent this assistant does not use (e.g. "tabular_query"); the rest of the graph is the same.
    disabled_tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # Whether this assistant may consult others for a question (#531): "none" (the default: what it answers from is what
    # its author chose), "all" (the closest of those the person using it may read), or "list" (those named in
    # consult_assistant_ids). It consults their collections, never their instructions, and never goes further than that.
    consult_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="none", server_default="none")
    consult_assistant_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    suggestions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    visibility: Mapped[CollectionVisibility] = mapped_column(
        Enum(CollectionVisibility, name="collection_visibility", create_type=False),
        nullable=False,
        default=CollectionVisibility.PRIVATE,
        server_default="PRIVATE",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    shares: Mapped[list["AssistantShare"]] = relationship(back_populates="assistant", cascade="all, delete-orphan")


class AssistantShare(UUIDMixin, TimestampMixin, Base):
    """An assistant shared with a person or a group - the same invitation as a collection's (CollectionShare): pending
    from the hash of what was typed, active when the person logs in (see app/core/sharing.py)."""

    __tablename__ = "assistant_shares"

    assistant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_type: Mapped[ShareSubjectType] = mapped_column(
        Enum(ShareSubjectType, name="share_subject_type", create_type=False), nullable=False
    )
    status: Mapped[ShareStatus] = mapped_column(
        Enum(ShareStatus, name="share_status", create_type=False),
        nullable=False,
        default=ShareStatus.PENDING,
        index=True,
    )
    # `read`: uses it. `write`: also changes it. Sharing it and deleting it stay with its author.
    permission: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SharePermission.READ, server_default="read"
    )
    subject_id: Mapped[str | None] = mapped_column(String, nullable=True)
    invited_identifier_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    display_hint: Mapped[str] = mapped_column(String, nullable=False)

    assistant: Mapped["Assistant"] = relationship(back_populates="shares")

    __table_args__ = (
        UniqueConstraint(
            "assistant_id", "subject_type", "invited_identifier_hash", name="uq_assistant_share_pending_identifier"
        ),
        UniqueConstraint("assistant_id", "subject_type", "subject_id", name="uq_assistant_share_active_subject"),
    )
