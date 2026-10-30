import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class OwuiSyncRunIn(BaseModel):
    """What the synchronisation worker reports about a run (#466): it started, ended with its account, or failed."""

    status: Literal["running", "done", "failed"]
    started_at: datetime | None = Field(default=None, description="Given when it starts, kept after that")
    account: dict[str, Any] | None = Field(default=None, description="finish_sync's account of what it did")
    error: str | None = None


class OwuiSyncRunOut(BaseModel):
    run_id: uuid.UUID
    # `running` also for a run that never ended: see `stalled`.
    status: Literal["running", "done", "failed"]
    started_at: datetime
    finished_at: datetime | None
    account: dict[str, Any] | None
    error: str | None
    # The run has been going on for longer than any can: it did not end, a worker died with it (the account is only
    # given by its last task).
    stalled: bool = False
    # It ended, but something in it went wrong: files, knowledge bases or groups in error, or a vector problem.
    with_problems: bool = False


class OwuiSyncStateOut(BaseModel):
    """What the administrators' page shows: the latest run, None when there never was one (the synchronisation is not
    set up, or has not run yet)."""

    latest: OwuiSyncRunOut | None
    running: bool


class SyncedCollectionOut(BaseModel):
    id: uuid.UUID
    name: str
    external_id: str
    # `copied`: read where it is and kept what Open WebUI has; `adopting`: Muffin is rebuilding its index to take it
    # over; `adopted`: it is Muffin's (#462).
    state: Literal["copied", "adopting", "adopted"]
    document_count: int
    summary_count: int
    synced_at: datetime | None
    problems: list[str]
