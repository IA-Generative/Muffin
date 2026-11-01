import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TokenUsageKind(enum.StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    # An image made by a provider (#518): costs in images and pixels, not in tokens of text.
    IMAGE = "image"


class TokenUsage(UUIDMixin, TimestampMixin, Base):
    """One LLM call made through the internal proxy (app/routers/internal_llm.py) - every chat
    completion and embedding a worker asks for, whatever it is for: the chat agent's nodes,
    document processing, evaluation, document editing.

    run_id/document_id/collection_id are what the worker said the call was for, kept as plain
    ids rather than foreign keys: consumption is history and must outlive a deleted document or
    collection. user_id is resolved from them once, at record time (see UsageService.record) -
    None when the call can't be tied to anyone (e.g. a collection-wide evaluation)."""

    __tablename__ = "token_usages"

    user_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # What the call was for: an agent graph node (analyze_query, generate_answer, ...) or a
    # worker task (summarize_document, generate_qa_window, ...).
    step: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[TokenUsageKind] = mapped_column(Enum(TokenUsageKind, name="token_usage_kind"), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What an image generation cost (#518): how many images, and their size in pixels (all of them, added).
    images: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pixels: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Shadows TimestampMixin's only to index it: every report filters on a period.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UserProfile(Base):
    """The name to show for a Keycloak subject in admin views (never a raw sub there, same rule
    as Report.user_display) - there is no users table, so it's refreshed from the identity every
    time the frontend asks who is logged in (GET /api/auth/me)."""

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    display: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    # The last time the person opened the application, and the groups of their token then: what a routine - which runs
    # without them - has of the person (#524). Never more than that: no token is kept.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
