"""When a routine (#524) runs: the dates of its rhythm, computed in the owner's time zone.

Pure functions, no database. The times of day are the owner's wall-clock times: "every day at 9:00" stays at 9:00
across the changes of daylight saving time. Whatever the rhythm, `advance` gives a date after `now`: a routine that was
missed during an outage runs once, not as many times as it missed dates."""

import calendar
import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Paris"
# The shortest and the longest interval a rhythm by hours may have: one minute is a loop, a year is a month's job.
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 31 * 24 * 60


class RoutineKind(enum.StrEnum):
    # Every `interval_minutes`, counted from the first run.
    INTERVAL = "interval"
    # Every day at `time_of_day`.
    DAILY = "daily"
    # On each of `weekdays` (0 = Monday) at `time_of_day`.
    WEEKLY = "weekly"
    # On `day_of_month` at `time_of_day`; a month that is shorter has it on its last day.
    MONTHLY = "monthly"


class InvalidScheduleError(ValueError):
    """The rhythm is not one that can be computed: the message says what is missing or out of bounds."""


@dataclass(frozen=True)
class Schedule:
    kind: RoutineKind
    timezone: str = DEFAULT_TIMEZONE
    interval_minutes: int | None = None
    time_of_day: time | None = None
    weekdays: Sequence[int] | None = None
    day_of_month: int | None = None


def validate(schedule: Schedule, min_interval_minutes: int = MIN_INTERVAL_MINUTES) -> None:
    """Raises InvalidScheduleError when the rhythm lacks what its kind needs or goes out of bounds."""
    try:
        ZoneInfo(schedule.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise InvalidScheduleError("Fuseau horaire inconnu.") from error
    if schedule.kind == RoutineKind.INTERVAL:
        if schedule.interval_minutes is None:
            raise InvalidScheduleError("Il faut un intervalle.")
        if schedule.interval_minutes < min_interval_minutes:
            raise InvalidScheduleError(f"L'intervalle minimal est de {min_interval_minutes} minutes.")
        if schedule.interval_minutes > MAX_INTERVAL_MINUTES:
            raise InvalidScheduleError("L'intervalle ne peut pas dépasser 31 jours.")
        return
    if schedule.time_of_day is None:
        raise InvalidScheduleError("Il faut une heure.")
    if schedule.kind == RoutineKind.WEEKLY and (
        not schedule.weekdays or any(day < 0 or day > 6 for day in schedule.weekdays)
    ):
        raise InvalidScheduleError("Il faut au moins un jour de la semaine (0 = lundi, 6 = dimanche).")
    if schedule.kind == RoutineKind.MONTHLY and (schedule.day_of_month is None or not 1 <= schedule.day_of_month <= 31):
        raise InvalidScheduleError("Il faut un jour du mois, de 1 à 31.")


def minimum_gap(schedule: Schedule) -> timedelta:
    """The shortest time between two runs of this rhythm: what the administrator's minimal interval is compared to."""
    if schedule.kind == RoutineKind.INTERVAL:
        return timedelta(minutes=schedule.interval_minutes or 0)
    if schedule.kind == RoutineKind.DAILY:
        return timedelta(days=1)
    if schedule.kind == RoutineKind.WEEKLY:
        days = sorted(set(schedule.weekdays or []))
        gaps = [(days[(i + 1) % len(days)] - day) % 7 or 7 for i, day in enumerate(days)] if days else [7]
        return timedelta(days=min(gaps))
    return timedelta(days=28)


def _at(day: date, at: time, zone: ZoneInfo) -> datetime:
    """That wall-clock time of that day, in UTC. A time that does not exist (the hour skipped in spring) takes the
    offset from before it, so it falls an hour later; one that exists twice (the hour repeated in autumn) is the
    first."""
    return datetime.combine(day, at, tzinfo=zone).astimezone(UTC)


def _on_day(schedule: Schedule, day: date) -> bool:
    if schedule.kind == RoutineKind.DAILY:
        return True
    if schedule.kind == RoutineKind.WEEKLY:
        return day.weekday() in (schedule.weekdays or ())
    last = calendar.monthrange(day.year, day.month)[1]
    return day.day == min(schedule.day_of_month or 1, last)


def next_after(schedule: Schedule, after: datetime) -> datetime:
    """The first date of a rhythm by the clock strictly after `after`. For a rhythm by hours there is no clock: it is
    counted from a date, see `first_run` and `advance`."""
    if schedule.kind == RoutineKind.INTERVAL:
        return after + timedelta(minutes=schedule.interval_minutes or MIN_INTERVAL_MINUTES)
    assert schedule.time_of_day is not None
    zone = ZoneInfo(schedule.timezone)
    day = after.astimezone(zone).date() - timedelta(days=1)
    # The longest wait for a date is a monthly one (two months at most, for a 31st); the margin is for a bad zone.
    for _ in range(400):
        day += timedelta(days=1)
        if not _on_day(schedule, day):
            continue
        candidate = _at(day, schedule.time_of_day, zone)
        if candidate > after:
            return candidate
    raise InvalidScheduleError("Aucune date ne correspond à ce rythme.")


def first_run(schedule: Schedule, now: datetime) -> datetime:
    """When a routine that has just been set runs first."""
    return next_after(schedule, now)


def advance(schedule: Schedule, scheduled: datetime, now: datetime) -> datetime:
    """When a routine that has just run (it was due at `scheduled`) runs next: after `now`, whatever it missed. A rhythm
    by hours goes on from the date it was due, so it does not drift."""
    if schedule.kind == RoutineKind.INTERVAL:
        interval = timedelta(minutes=schedule.interval_minutes or MIN_INTERVAL_MINUTES)
        return scheduled + interval * ((now - scheduled) // interval + 1)
    return next_after(schedule, now)


def upcoming(schedule: Schedule, now: datetime, count: int = 5) -> list[datetime]:
    """The next dates, for the person to check a rhythm before keeping it."""
    dates = [first_run(schedule, now)]
    while len(dates) < count:
        dates.append(advance(schedule, dates[-1], dates[-1]))
    return dates
