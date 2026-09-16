import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class FeedbackReasonCode(enum.StrEnum):
    INCORRECT_ANSWER = "incorrect_answer"
    NOT_USEFUL = "not_useful"
    QUESTIONABLE_SOURCES = "questionable_sources"
    INAPPROPRIATE_TONE = "inappropriate_tone"
    OTHER = "other"


class FeedbackSourceRole(enum.StrEnum):
    VALIDATED = "validated"  # existing message source confirmed as correct
    ADDED = "added"  # new source suggested by the reviewer


class Feedback(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "feedbacks"

    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Keycloak subject (sub) claim of the reviewer.
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped["Message"] = relationship(back_populates="feedbacks")  # noqa: F821
    reasons: Mapped[list["FeedbackReason"]] = relationship(back_populates="feedback", cascade="all, delete-orphan")
    sources: Mapped[list["FeedbackSource"]] = relationship(back_populates="feedback", cascade="all, delete-orphan")


class FeedbackReason(Base):
    """Detail table: the (multiple) reason codes selected for a feedback."""

    __tablename__ = "feedback_reasons"

    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedbacks.id", ondelete="CASCADE"), primary_key=True)
    reason: Mapped[FeedbackReasonCode] = mapped_column(
        Enum(FeedbackReasonCode, name="feedback_reason_code"), primary_key=True
    )

    feedback: Mapped["Feedback"] = relationship(back_populates="reasons")


class FeedbackSource(Base):
    """Link table: sources attached to a feedback, either validated or newly added."""

    __tablename__ = "feedback_sources"

    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feedbacks.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[FeedbackSourceRole] = mapped_column(
        Enum(FeedbackSourceRole, name="feedback_source_role"), primary_key=True
    )

    feedback: Mapped["Feedback"] = relationship(back_populates="sources")
    source: Mapped["Source"] = relationship()  # noqa: F821
