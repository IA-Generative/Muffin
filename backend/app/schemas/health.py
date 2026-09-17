from typing import Any

from pydantic import BaseModel


class Health(BaseModel):
    name: str
    status: str
    extras: dict[str, Any] | None = None


class HealthReport(BaseModel):
    name: str
    version: str
    up_time: str
    status: str
    dependencies: list[Health]
