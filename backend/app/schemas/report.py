import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.report import ReportStatus, ReportType


class ReportOut(BaseModel):
    id: uuid.UUID
    type: ReportType
    title: str
    description: str
    status: ReportStatus
    screenshot_url: str | None
    admin_response: str | None
    created_at: datetime
    updated_at: datetime


class ReportAdminOut(ReportOut):
    user_display: str
    responded_by: str | None


class ReportUpdate(BaseModel):
    status: ReportStatus
    admin_response: str | None = None
