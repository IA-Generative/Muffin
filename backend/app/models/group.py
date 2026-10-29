import enum
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
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


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    # Keycloak subject (sub) claim, like Collection.owner_id.
    user_id: Mapped[str] = mapped_column(String, primary_key=True, index=True, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())
