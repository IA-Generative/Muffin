import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_name: str
    status: str
    document_id: uuid.UUID | None
    document_name: str | None
    collection_id: uuid.UUID | None
    collection_name: str | None
    parent_id: uuid.UUID | None
    created_at: datetime


class TaskLogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Pass the last one back as `after` to get only the lines logged since.
    id: int
    task_name: str
    ts: datetime
    level: str
    message: str


class TaskLogsOut(BaseModel):
    entries: list[TaskLogEntryOut]
    # More lines than one page already: ask again right away, with the last id as `after`.
    has_more: bool
