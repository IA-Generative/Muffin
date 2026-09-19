import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class DiscussionFeedback(UUIDMixin, TimestampMixin, Base):
    """A human-authored quality judgment over a whole conversation - the manual counterpart to
    DiscussionScore (which is LLM-generated). The user is prompted after enough turns (see
    frontend DiscussionFeedbackPrompt) to rate the conversation: overall satisfaction, whether
    the conversation felt coherent, and a free-text comment. Unlike DiscussionScore, this is
    keyed by (conversation_id, user_id) so each user has at most one feedback per conversation,
    upserted on re-submit."""

    __tablename__ = "discussion_feedbacks"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Keycloak sub - same as Feedback.user_id, the reviewer's identity.
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # 1-5: overall satisfaction with the conversation (5 = excellent, 1 = very poor).
    rating: Mapped[int] = mapped_column(Integer, nullable=False)

    # Whether the conversation felt coherent across turns (contradictions, topic drift...).
    coherent: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # 0.0-1.0: how well the assistant used the conversation's context (follow-up references,
    # prior answers...). Optional because a user may not have a strong opinion on this.
    context_usage_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Free-text comment, optional.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="discussion_feedbacks")  # noqa: F821
