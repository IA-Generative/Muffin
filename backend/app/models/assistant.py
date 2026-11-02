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
    # Exposed as a "model" of the OpenAI-compatible API (`muffin:assistant:<id>`, #513): still only to someone who may
    # already use this assistant - this only lets them reach it through that API too, it opens nothing new.
    expose_as_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Exposed as an A2A agent (#a2a): its own agent card and endpoint, reached with a personal API key (same rule as
    # above) or the dedicated token below - for an external agent that is not a Muffin user at all, run with the
    # rights of this assistant's owner (never anyone else's).
    expose_as_a2a: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # `version$HMAC-SHA256(pepper, token)`, the same scheme as a personal API key (app/core/api_keys.py) - only ever
    # compared against, never read back. None while expose_as_a2a has no dedicated token (API-key callers only).
    a2a_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The first characters of the token, to recognise it by - never enough to use it.
    a2a_token_prefix: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The owner's groups when the token was last (re)made - a call with it has no session to read them from live, the
    # same tradeoff as ApiKey.owner_groups. Muffin's own groups are not frozen here: looked up live at each call
    # (GroupRepository), as for a personal API key.
    a2a_owner_groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
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
