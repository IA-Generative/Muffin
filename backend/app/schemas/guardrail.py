import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.config import GuardrailSettings
from app.models.guardrail import (
    Aggregation,
    Enforcement,
    GuardrailType,
    OnError,
    OnIncomplete,
    WaitStrategy,
)

_settings = GuardrailSettings()


class GuardrailBody(BaseModel):
    """What an administrator sets on a guardrail: the same on creation and, field by field, on change."""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    type: GuardrailType
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    enforcement: Enforcement = Enforcement.MONITOR
    stage: int = Field(default=1, ge=1, le=9)
    timeout_ms: int = Field(default=2000, ge=20, le=_settings.GUARDRAILS_TIMEOUT_LIMIT_MS)
    on_error: OnError = OnError.FAIL_OPEN
    critical: bool = False
    scope_groups: list[str] = Field(default_factory=list, max_length=50)
    scope_assistants: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    refusal_message: str | None = Field(default=None, max_length=1000)
    category_label: str | None = Field(default=None, max_length=100)
    # The key of a service of type `http`: written, never read back.
    api_key: str | None = Field(default=None, max_length=2000)


class GuardrailCreate(GuardrailBody):
    pass


class GuardrailUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    enforcement: Enforcement | None = None
    stage: int | None = Field(default=None, ge=1, le=9)
    timeout_ms: int | None = Field(default=None, ge=20, le=_settings.GUARDRAILS_TIMEOUT_LIMIT_MS)
    on_error: OnError | None = None
    critical: bool | None = None
    scope_groups: list[str] | None = Field(default=None, max_length=50)
    scope_assistants: list[uuid.UUID] | None = Field(default=None, max_length=50)
    refusal_message: str | None = Field(default=None, max_length=1000)
    category_label: str | None = Field(default=None, max_length=100)
    # What is sent is what changes: an empty text clears the refusal or the label.
    clear_refusal_message: bool = False
    clear_category_label: bool = False
    api_key: str | None = Field(default=None, max_length=2000)
    clear_key: bool = False

    @model_validator(mode="after")
    def _one_way_to_set_the_key(self) -> "GuardrailUpdate":
        if self.clear_key and self.api_key:
            raise ValueError("api_key and clear_key cannot go together")
        return self


class GuardrailOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    type: GuardrailType
    config: dict[str, Any]
    enabled: bool
    enforcement: Enforcement
    stage: int
    timeout_ms: int
    on_error: OnError
    critical: bool
    scope_groups: list[str]
    scope_assistants: list[str]
    refusal_message: str | None
    category_label: str | None
    # A key is stored for the service. Never the key.
    has_key: bool
    preset_key: str | None
    position: int
    version: int
    updated_by: str | None
    updated_at: datetime


class PolicyOut(BaseModel):
    aggregation: Aggregation
    quorum: int
    wait_strategy: WaitStrategy
    timeout_ms: int
    on_incomplete: OnIncomplete
    min_verdicts: int
    show_category: bool
    default_refusal: str
    updated_at: datetime


class PolicyUpdate(BaseModel):
    aggregation: Aggregation | None = None
    quorum: int | None = Field(default=None, ge=1, le=50)
    wait_strategy: WaitStrategy | None = None
    timeout_ms: int | None = Field(default=None, ge=50, le=_settings.GUARDRAILS_TIMEOUT_LIMIT_MS)
    on_incomplete: OnIncomplete | None = None
    min_verdicts: int | None = Field(default=None, ge=0, le=50)
    show_category: bool | None = None
    default_refusal: str | None = Field(default=None, min_length=1, max_length=1000)


class ReorderIn(BaseModel):
    # Every guardrail, in the order wanted: the stage of each is its own, the order is inside a stage.
    ids: list[uuid.UUID] = Field(max_length=_settings.GUARDRAILS_MAX)


class ProbeIn(BaseModel):
    # A text typed by the administrator to see what the guardrails say. It is never kept and makes no run.
    text: str = Field(min_length=1, max_length=_settings.GUARDRAILS_TEXT_MAX_CHARS)
    # Some guardrails only; empty: all of them, the ones that are disabled included.
    guardrail_ids: list[uuid.UUID] = Field(default_factory=list, max_length=_settings.GUARDRAILS_MAX)


class ProbeVerdictOut(BaseModel):
    guardrail_id: uuid.UUID | None
    name: str
    enabled: bool
    stage: int
    enforcement: Enforcement
    # `clear`, `flagged`, `error`, `timeout`, `cancelled` or `not_run` (a later stage the request did not reach).
    verdict: str
    category: str | None
    score: float | None
    latency_ms: int
    # What it led to in the decision, for the guardrails that are enabled.
    action: str


class ProbeOut(BaseModel):
    outcome: str
    message: str | None
    # The text that would go on to the models, masked when a guardrail redacts.
    text: str
    incomplete: bool
    verdicts: list[ProbeVerdictOut]


class GuardrailStatOut(BaseModel):
    guardrail_id: uuid.UUID | None
    name: str
    day: datetime
    evaluated: int
    flagged: int
    blocked: int
    failed: int
    avg_latency_ms: float
    max_latency_ms: int


class GuardrailStatsOut(BaseModel):
    days: int
    requests_checked: int
    requests_blocked: int
    rows: list[GuardrailStatOut]


class AuditOut(BaseModel):
    id: uuid.UUID
    guardrail_id: uuid.UUID | None
    guardrail_name: str
    action: str
    user_display: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    created_at: datetime


class RunGuardrailOut(BaseModel):
    """What the guardrails decided for a run, for the agent that is about to read the request. Names, categories and
    scores stay here: the agent is told what to do, not why."""

    # `continue`, `continue_with_redaction`, `continue_with_warning` or `block`.
    outcome: str
    # The request as the models may read it: masked when it had to be.
    query: str
    # The refusal, or the notice that goes with a warning or a masking.
    message: str | None
    checked: int
    flagged: int
