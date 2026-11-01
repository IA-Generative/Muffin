from datetime import date

from pydantic import BaseModel


class UsageSums(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # Images made by a provider (#518) and their size in pixels: what they cost is not in tokens.
    images: int = 0
    pixels: int = 0
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


class ExecutionSums(BaseModel):
    count: int = 0
    duration_seconds: float = 0.0
    cpu_seconds: float = 0.0
    # The most memory one execution held; 0 for a node, which has none of its own.
    peak_rss_bytes: int = 0
    # Estimated, see EnergySettings: never a measure.
    energy_wh: float = 0.0


class ExecutionStep(ExecutionSums):
    kind: str
    step: str


class ExecutionDay(ExecutionSums):
    day: date


class ExecutionUser(ExecutionSums):
    user_id: str | None
    display: str | None


class EnergyAssumptions(BaseModel):
    watts_per_core: float
    watts_per_gb: float
    pue: float


class ExecutionOut(BaseModel):
    """What the worker tasks cost the machines that ran them. `totals` and `by_day` count the tasks only:
    the nodes of the agent run inside a task, `by_step` lists both (each with its kind)."""

    totals: ExecutionSums
    by_step: list[ExecutionStep]
    by_day: list[ExecutionDay]
    by_user: list[ExecutionUser]
    assumptions: EnergyAssumptions


class RoutineUsage(BaseModel):
    """What the routines asked of the agent (#524), apart from the rest: runs that were made, and their tokens."""

    runs: int
    total_tokens: int


class UsageOut(BaseModel):
    days: int
    totals: UsageSums
    by_step: list[StepUsage]
    by_day: list[DayUsage]
    by_model: list[ModelUsage]
    # Administrators only - always empty on a user's own report.
    by_user: list[UserUsage]
    execution: ExecutionOut
    routines: RoutineUsage = RoutineUsage(runs=0, total_tokens=0)
