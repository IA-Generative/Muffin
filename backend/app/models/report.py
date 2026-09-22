import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ReportType(enum.StrEnum):
    BUG = "bug"
    IDEA = "idea"
    QUESTION = "question"


class ReportStatus(enum.StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"


class Report(UUIDMixin, TimestampMixin, Base):
    """A free-form bug/idea/question signalé by a user from the user menu (§148) - distinct from
    Feedback (thumbs up/down on one specific run's answer): a Report isn't tied to a run, can be
    about anything, and carries a status/reply lifecycle an admin drives."""

    __tablename__ = "reports"

    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # Resolved once at creation time, same reasoning as Document.added_by_display - never a raw
    # Keycloak sub in the admin UI, and stable even if the reporter later changes their profile.
    user_display: Mapped[str] = mapped_column(String, nullable=False)

    type: Mapped[ReportType] = mapped_column(Enum(ReportType, name="report_type"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), nullable=False, default=ReportStatus.NEW
    )

    # Optional screenshot attached at submission - RustFS storage key, never the URL itself (see
    # app/core/storage.py, same pattern as Document.storage_key).
    screenshot_key: Mapped[str | None] = mapped_column(String, nullable=True)

    # A single reply field, not a full thread - v1 scope decision (§148: "probablement une seule
    # réponse pour une v1, extensible en fil plus tard si besoin").
    admin_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by: Mapped[str | None] = mapped_column(String, nullable=True)
