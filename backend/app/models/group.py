import enum
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ResourceSource(enum.StrEnum):
    """Where a resource comes from: made in Muffin, or copied from another system (#453). A copied one is read
    only here - only the synchronisation changes it - and carries that system's id in `external_id`."""

    MUFFIN = "muffin"
    OWUI = "owui"


class Group(UUIDMixin, TimestampMixin, Base):
    """A group of people a collection can be shared with, next to the groups of the Keycloak token (#453).

    Its members are Keycloak subjects. A user's groups are those of their token plus the ones they are a
    member of here (a group's id is what a share points to - it never looks like a token's group path)."""

    __tablename__ = "groups"
    __table_args__ = (
        # One copy per resource of the other system; the groups made in Muffin have no external id.
        Index(
            "uq_groups_source_external_id",
            "source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ResourceSource.MUFFIN, server_default="muffin"
    )
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Keycloak subject of the person who made it and manages it (#455). None for a group copied from another
    # system: nobody owns it, only the synchronisation changes it.
    owner_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)


class MemberStatus(enum.StrEnum):
    ACTIVE = "active"
    PENDING = "pending"


class GroupMember(UUIDMixin, Base):
    """Someone in a group: a Keycloak subject, or - until they sign in - an invitation made by the hash of their
    email, never looked up, like a collection share (app/core/sharing.py, docs/collection-sharing.md)."""

    __tablename__ = "group_members"
    __table_args__ = (
        # NULLs are never equal in a unique constraint: these only bind the rows that have the column.
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
        UniqueConstraint("group_id", "invited_identifier_hash", name="uq_group_members_pending_identifier"),
        CheckConstraint(
            "(status = 'active' AND user_id IS NOT NULL)"
            " OR (status = 'pending' AND invited_identifier_hash IS NOT NULL)",
            name="ck_group_members_status_fields",
        ),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=False)
    # Keycloak subject (sub) claim, like Collection.owner_id. None while the invitation is pending.
    user_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MemberStatus.ACTIVE, server_default="active", index=True
    )
    # HMAC of the normalised email invited, cleared once the person signed in and the member is active.
    invited_identifier_hash: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # "j***@e***.com": what the owner sees of a pending invitation, never the address again.
    display_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
