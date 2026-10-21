from datetime import date

from pydantic import BaseModel


class UsageSums(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0


class StepUsage(UsageSums):
    step: str


class DayUsage(UsageSums):
    day: date


class ModelUsage(UsageSums):
    model: str


class UserUsage(UsageSums):
    # None for the calls that couldn't be tied to anyone (e.g. a discussion score).
    user_id: str | None
    display: str | None


class UsageOut(BaseModel):
    days: int
    totals: UsageSums
    by_step: list[StepUsage]
    by_day: list[DayUsage]
    by_model: list[ModelUsage]
    # Administrators only - always empty on a user's own report.
    by_user: list[UserUsage]
