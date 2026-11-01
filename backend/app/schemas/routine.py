import uuid
from datetime import datetime, time

from pydantic import BaseModel, Field, model_validator

from app.core import routine_schedule
from app.core.routine_schedule import DEFAULT_TIMEZONE, RoutineKind
from app.models.routine import RoutineCondition, RoutineNotify, RoutineResultMode, RoutineRunStatus, RoutineState

QUESTION_MAX_CHARS = 4000


class ScheduleIn(BaseModel):
    kind: RoutineKind
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=64)
    interval_minutes: int | None = Field(default=None, ge=1)
    time_of_day: time | None = None
    # 0 = Monday.
    weekdays: list[int] | None = Field(default=None, max_length=7)
    day_of_month: int | None = Field(default=None, ge=1, le=31)


class ScheduleOut(ScheduleIn):
    pass


class RoutineBody(BaseModel):
    """What a person sets: the same on creation and, field by field, on change."""

    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=QUESTION_MAX_CHARS)
    # Empty, and no assistant: everything the person may read, as in the chat.
    collection_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    include_descendants: bool = True
    assistant_id: uuid.UUID | None = None
    web_search: bool = False
    schedule: ScheduleIn
    condition: RoutineCondition = RoutineCondition.ALWAYS
    result_mode: RoutineResultMode = RoutineResultMode.NEW_CONVERSATION
    notify: RoutineNotify = RoutineNotify.ALWAYS


class RoutineCreate(RoutineBody):
    pass


class RoutineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    question: str | None = Field(default=None, min_length=1, max_length=QUESTION_MAX_CHARS)
    collection_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    include_descendants: bool | None = None
    assistant_id: uuid.UUID | None = None
    # Sent to remove the assistant: `assistant_id` alone cannot tell "not given" from "none".
    clear_assistant: bool = False
    web_search: bool | None = None
    schedule: ScheduleIn | None = None
    condition: RoutineCondition | None = None
    result_mode: RoutineResultMode | None = None
    notify: RoutineNotify | None = None

    @model_validator(mode="after")
    def _one_way_to_set_the_assistant(self) -> "RoutineUpdate":
        if self.clear_assistant and self.assistant_id is not None:
            raise ValueError("assistant_id and clear_assistant cannot go together")
        return self


class RoutineRunOut(BaseModel):
    id: uuid.UUID
    status: RoutineRunStatus
    skip_reason: str | None
    trigger: str
    error: str | None
    note: str | None
    total_tokens: int
    conversation_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: int | None


class RoutineOut(BaseModel):
    id: uuid.UUID
    name: str
    question: str
    collection_ids: list[uuid.UUID]
    include_descendants: bool
    assistant_id: uuid.UUID | None
    web_search: bool
    schedule: ScheduleOut
    condition: RoutineCondition
    result_mode: RoutineResultMode
    notify: RoutineNotify
    state: RoutineState
    # `failures`, `inactive` or `admin` when suspended.
    suspended_reason: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    consecutive_failures: int
    conversation_id: uuid.UUID | None
    last_run: RoutineRunOut | None
    created_at: datetime


class RoutineStatusOut(BaseModel):
    """What the page needs before listing anything: whether the function is on, and the limits the person is held to."""

    enabled: bool
    max_active: int
    min_interval_minutes: int
    max_runs_per_day: int
    active: int
    runs_today: int


class PreviewOut(BaseModel):
    dates: list[datetime]


class TriggerOut(BaseModel):
    run: RoutineRunOut


class RoutineSettingsOut(BaseModel):
    enabled: bool
    max_active_per_user: int
    min_interval_minutes: int
    max_runs_per_user_per_day: int
    max_concurrent: int
    max_consecutive_failures: int
    inactive_days: int
    run_timeout_minutes: int


class RoutineSettingsUpdate(BaseModel):
    enabled: bool | None = None
    max_active_per_user: int | None = Field(default=None, ge=1, le=100)
    min_interval_minutes: int | None = Field(default=None, ge=routine_schedule.MIN_INTERVAL_MINUTES, le=10080)
    max_runs_per_user_per_day: int | None = Field(default=None, ge=1, le=1000)
    max_concurrent: int | None = Field(default=None, ge=1, le=100)
    max_consecutive_failures: int | None = Field(default=None, ge=1, le=100)
    inactive_days: int | None = Field(default=None, ge=1, le=3650)
    run_timeout_minutes: int | None = Field(default=None, ge=1, le=240)


class AdminRoutineOut(BaseModel):
    """A routine as an administrator sees it: who, how often and how much - never its question nor its answers."""

    id: uuid.UUID
    name: str
    owner_display: str
    schedule: ScheduleOut
    state: RoutineState
    suspended_reason: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    consecutive_failures: int
    last_status: RoutineRunStatus | None
    tokens_30_days: int
    created_at: datetime
