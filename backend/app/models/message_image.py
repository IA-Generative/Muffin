import uuid

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

ORIGIN_GENERATED = "generated"
ORIGIN_ATTACHED = "attached"


class MessageImage(UUIDMixin, TimestampMixin, Base):
    """An image of the chat, stored by Muffin: one a model made for a person (#518), or one the person attached to
    their message for the model to read (#512).

    Either way it is the conversation's - read by its owner only, through the backend (never a link to the bucket),
    and deleted with the conversation - and it belongs to the message that shows it. The answer of an image provider
    is never given on as it is (an address of its own expires and points at a third party), and an image is checked
    on its bytes before it is kept.

    An attached image is first *staged*: uploaded when the person chooses it, before there is a message - or even a
    conversation - to hold it, so `conversation_id` and `message_id` are empty until the run that carries it is made."""

    __tablename__ = "message_images"

    # "generated" or "attached".
    origin: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # The run that made it, when the assistant did (the tool `generer_image`): the image belongs to the run first,
    # and to the message once the run's answer is one - like a chart. Empty for an image asked for with the mode
    # «Image», and for an attached one.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # What the model was asked to draw, and with which model: for a generated image only.
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # RustFS key: images/{conversation_id}/{image_id}.{png|jpg|webp} for a generated one, and
    # images/attached/{image_id}.* for an attached one (which had no conversation yet when it was stored).
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
