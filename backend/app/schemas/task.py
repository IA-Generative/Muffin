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
    # Tail of the raw loguru output the worker produced for this task, always
    # populated (not just on failure) - see app/models/task.py.
    log_preview: str
    has_more_logs: bool


class TaskLogsOut(BaseModel):
    id: uuid.UUID
    logs: str
