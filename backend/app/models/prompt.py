import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class PromptVersion(UUIDMixin, TimestampMixin, Base):
    """One version of one of the agent's system prompts (see the `_SYSTEM_PROMPT` constants in
    worker/agent_execution/app/graph/nodes/*.py, which this table replaces as the source of
    truth). `name` is the node's own prompt slug (e.g. "generate_answer") - never a display
    title. Only one row per name may have is_active=True at a time (enforced in
    PromptRepository.activate, not a DB constraint: a partial unique index would need a raw
    migration and the invariant is only ever touched through that one method)."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_versions_name_version"),)

    name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RunPromptUsage(UUIDMixin, TimestampMixin, Base):
    """Which prompt version answered which run (§ issue #96 traceability) - one row per prompt
    actually used, not per node call: a run that replans twice still used the same
    replan_research prompt version both times, so it's recorded once. Written in one batch at
    the end of the run (see agent_service.py::_finalize), same timing as Run.grounding_valid."""

    __tablename__ = "run_prompt_usages"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=False)
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="CASCADE"), index=True, nullable=False
    )
