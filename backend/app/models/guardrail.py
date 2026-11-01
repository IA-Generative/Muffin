import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class GuardrailType(enum.StrEnum):
    # Code, no model: patterns, lists of terms, a length.
    RULES = "rules"
    # A model of the hub classifies the request, in a strict JSON.
    LLM = "llm"
    # A service outside, with a contract that is fixed.
    HTTP = "http"


class Enforcement(enum.StrEnum):
    # A request that is flagged stops here.
    BLOCK = "block"
    # It goes on, and the person is told.
    WARN = "warn"
    # The sensitive part is masked before the text goes to a model; the request goes on.
    REDACT = "redact"
    # Nothing is visible: the verdict is only recorded, to measure the false positives before applying a rule.
    MONITOR = "monitor"


class OnError(enum.StrEnum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


class Aggregation(enum.StrEnum):
    # One blocking guardrail that flags is enough to stop.
    ANY = "any"
    # At least `quorum` of the blocking guardrails of a stage must flag.
    QUORUM = "quorum"


class WaitStrategy(enum.StrEnum):
    # Every verdict is waited for, so that everything that was seen is recorded.
    WAIT_ALL = "wait_all"
    # As soon as the blocking guardrails settle it, the others are cancelled.
    FIRST_BLOCK = "first_block"


class OnIncomplete(enum.StrEnum):
    CONTINUE = "continue"
    BLOCK = "block"


class Guardrail(UUIDMixin, TimestampMixin, Base):
    """A guardrail on the input (#516): defined by an administrator and no one else, run before anything of the request
    goes to a model. `config` holds what its type needs and never a secret: the key of a service is a `StoredSecret`."""

    __tablename__ = "guardrails"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    type: Mapped[GuardrailType] = mapped_column(Enum(GuardrailType, name="guardrail_type"), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    enforcement: Mapped[Enforcement] = mapped_column(
        Enum(Enforcement, name="guardrail_enforcement"), nullable=False, default=Enforcement.MONITOR
    )
    # The guardrails of stage 1 go first; those of stage 2 only if the request passed stage 1.
    stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=2000, server_default="2000")
    on_error: Mapped[OnError] = mapped_column(
        Enum(OnError, name="guardrail_on_error"), nullable=False, default=OnError.FAIL_OPEN
    )
    # A critical guardrail that cannot give its verdict stops the request, whatever the rest says.
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Keycloak groups or groups of Muffin, and assistants (ids): empty both means everyone. A guardrail applies to a
    # request that is in one of them.
    scope_groups: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    scope_assistants: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # What the person is told when it blocks (or warns). Neutral by default, and never the rule.
    refusal_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A general category the person may be told ("données personnelles"), shown only when the policy allows it.
    category_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # The key of a service of type `http`, encrypted (`StoredSecret`, purpose `guardrail-http-key`), never read back.
    secret_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # The guardrails that come with the application, by key: they are made once and an administrator may change or
    # delete them.
    preset_key: Mapped[str | None] = mapped_column(String(48), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Raised at each change: a result says which version of the guardrail judged.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)


class GuardrailPolicy(Base):
    """How the guardrails as a whole decide (#516): one row (id is always 1), admin-only."""

    __tablename__ = "guardrail_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    aggregation: Mapped[Aggregation] = mapped_column(
        Enum(Aggregation, name="guardrail_aggregation"), nullable=False, default=Aggregation.ANY
    )
    quorum: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    wait_strategy: Mapped[WaitStrategy] = mapped_column(
        Enum(WaitStrategy, name="guardrail_wait_strategy"), nullable=False, default=WaitStrategy.WAIT_ALL
    )
    # The longest the whole check may take (milliseconds): what is not answered by then is a timeout.
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=2000, server_default="2000")
    on_incomplete: Mapped[OnIncomplete] = mapped_column(
        Enum(OnIncomplete, name="guardrail_on_incomplete"), nullable=False, default=OnIncomplete.CONTINUE
    )
    # How many blocking guardrails must have given a real verdict (not an error, not a timeout); fewer is "incomplete".
    min_verdicts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Whether a refusal may name the general category of a guardrail ("données personnelles") or stays neutral.
    show_category: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # The message of a refusal when the guardrail has none of its own.
    default_refusal: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=(
            "Votre demande ne peut pas être traitée : elle ne respecte pas la politique d'usage de cette application."
        ),
    )
    presets_made: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GuardrailResult(UUIDMixin, Base):
    """What a guardrail said of a request: the verdict, the category, the score, the time, and what was done.
    **Never the text of the person.** Plain ids for the run and the guardrail: this is history, and it outlives both."""

    __tablename__ = "guardrail_results"

    run_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    guardrail_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=True)
    guardrail_name: Mapped[str] = mapped_column(String(100), nullable=False)
    guardrail_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stage: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enforcement: Mapped[str] = mapped_column(String(16), nullable=False)
    # `clear`, `flagged`, `error`, `timeout` or `cancelled`.
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What was done because of it: `blocked`, `redacted`, `warned`, `monitored`, `ignored` (an error let through) or
    # `none`.
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class GuardrailAudit(UUIDMixin, Base):
    """Who changed the guardrails, when, and what they were before and after: a change alters what the application does
    for everyone. A secret is never in it."""

    __tablename__ = "guardrail_audit"

    guardrail_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=True)
    guardrail_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # `created`, `updated`, `deleted`, `reordered` or `policy`.
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    user_display: Mapped[str] = mapped_column(String, nullable=False, default="")
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
