import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.user_memory import MemoryKind, MemoryOrigin


class MemoryItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: MemoryKind
    key: str
    value: str
    origin: MemoryOrigin
    confidence: float
    evidence_count: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None


class MemoryOut(BaseModel):
    # Whether the person's memory is on, and whether the administrator allows it at all.
    enabled: bool
    available: bool
    max_items: int
    value_max_chars: int
    items: list[MemoryItemOut]


class MemoryItemCreate(BaseModel):
    kind: MemoryKind = MemoryKind.FACT
    value: str = Field(max_length=2000)


class MemoryItemUpdate(BaseModel):
    value: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


class MemorySettingsUpdate(BaseModel):
    enabled: bool


class MemoryExportOut(BaseModel):
    exported_at: datetime
    enabled: bool
    items: list[MemoryItemOut]


class MemoryStatsOut(BaseModel):
    """What an administrator sees of the memories: counts, never a word of what is remembered."""

    available: bool
    people: int
    items: int
    turned_off: int


# What a run reads (internal).
class RunMemoryItem(BaseModel):
    id: uuid.UUID
    kind: MemoryKind
    value: str


class RunHabit(BaseModel):
    """A collection the person is used to (#286), for the routing: its weight is 0 to 1."""

    collection_id: uuid.UUID
    weight: float


class RunMemoryOut(BaseModel):
    # `on`: used and may be written. Otherwise why not: `temporary` (this conversation), `unavailable` (an assistant, a
    # routine, the API), `disabled` (the person turned it off) or `suspended` (the administrator did).
    state: str
    items: list[RunMemoryItem] = []
    habits: list[RunHabit] = []


class HabitsOut(BaseModel):
    """The collections to propose first to a person, the most used first (#286)."""

    collection_ids: list[uuid.UUID]


class RunMemoryCommand(BaseModel):
    action: str = Field(pattern="^(remember|forget|show)$")
    kind: MemoryKind = MemoryKind.FACT
    text: str = Field(default="", max_length=2000)


class RunMemoryCommandOut(BaseModel):
    # `saved`, `updated`, `deleted`, `not_found`, `several`, `listed`, `refused`, or the state when nothing can be done.
    outcome: str
    message: str


class RunMemoryUsed(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)
