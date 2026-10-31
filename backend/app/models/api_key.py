from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

SCOPE_CHAT = "chat"
SCOPE_SEARCH = "search"
SCOPES = (SCOPE_CHAT, SCOPE_SEARCH)


class ApiKey(UUIDMixin, TimestampMixin, Base):
    """A personal API key (#521, #513): what a script or another tool presents to act as its owner, in place of the
    short-lived token of a session. Only the hash of the key is kept - see app/core/api_keys.py."""

    __tablename__ = "api_keys"

    # Keycloak subject of the owner.
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # `sk-muffin-` and the first characters of the key: enough to tell one from another, never enough to use it.
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    # `version$HMAC-SHA256(pepper, key)`.
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # What the owner was when last seen logged in: a key carries no token to read it from. Their Muffin groups are not
    # kept here - they are looked up at each call, like for a session.
    owner_email: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now
