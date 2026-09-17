import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")  # noqa: F821
    sources: Mapped[list["Source"]] = relationship(  # noqa: F821
        secondary="message_sources", back_populates="messages"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(  # noqa: F821
        back_populates="message", cascade="all, delete-orphan"
    )
