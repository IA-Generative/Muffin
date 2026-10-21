import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.index_rebuild import IndexRebuildStatus


class IndexRebuildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collection_id: uuid.UUID
    status: IndexRebuildStatus
    target_model: str
    previous_model: str
    total_points: int
    done_points: int
    error: str | None
    created_at: datetime
    swapped_at: datetime | None
    finished_at: datetime | None


# -- what the worker exchanges with the backend (internal) ---------------------------------------

PointKind = Literal["chunk", "summary", "qa"]


class RebuildPointOut(BaseModel):
    id: uuid.UUID
    kind: PointKind
    text: str


class RebuildPlanOut(BaseModel):
    status: IndexRebuildStatus
    collection_id: uuid.UUID
    # The model every vector of this rebuild is made with.
    model: str
    # The next points to embed; `remaining` counts all of them, these are the first.
    points: list[RebuildPointOut]
    remaining: int = 0


class RebuildPointIn(BaseModel):
    id: uuid.UUID
    kind: PointKind
    # The text the vector was made from - checked against the current one before it is stored.
    text: str
    embedding: list[float]


class RebuildVectorsIn(BaseModel):
    model: str
    points: list[RebuildPointIn] = Field(max_length=500)


class RebuildFailureIn(BaseModel):
    error: str
