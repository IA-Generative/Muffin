from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    # Keycloak subject (sub) claim; no local users table, auth is delegated to Keycloak.
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)

    messages: Mapped[list["Message"]] = relationship(  # noqa: F821
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
