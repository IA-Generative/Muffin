"""Time tool for the research agent.

Provides the LLM with precise temporal context (current time down to the second) and
pre-computed relative periods (today, this week, last month, etc.) so it can reason about
time-dependent queries without guessing the current date.

Uses only stdlib (datetime + zoneinfo) — no external dependencies needed.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Paris"


def _now(tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    """Current datetime in the given IANA timezone, precise to the second."""
    return datetime.now(ZoneInfo(tz_name))


def _iso(dt: datetime) -> str:
    """ISO 8601 with timezone offset, second precision."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def _start_of_week(dt: datetime) -> datetime:
    """Monday-based start of the week containing *dt*."""
    return _start_of_day(dt - timedelta(days=dt.weekday()))


def _end_of_week(dt: datetime) -> datetime:
    """Sunday-based end of the week containing *dt*."""
    return _end_of_day(dt + timedelta(days=6 - dt.weekday()))


def _start_of_month(dt: datetime) -> datetime:
    return _start_of_day(dt.replace(day=1))


def _end_of_month(dt: datetime) -> datetime:
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return _end_of_day(dt.replace(day=last_day))


def _start_of_year(dt: datetime) -> datetime:
    return _start_of_day(dt.replace(month=1, day=1))


def _end_of_year(dt: datetime) -> datetime:
    return _end_of_day(dt.replace(month=12, day=31))


def _period_range(now: datetime, period: str, n: int = 0) -> tuple[datetime, datetime]:
    """Return (start, end) for a named relative period, second-precise."""
    if period == "today":
        return _start_of_day(now), _end_of_day(now)
    if period == "yesterday":
        d = now - timedelta(days=1)
        return _start_of_day(d), _end_of_day(d)
    if period == "tomorrow":
        d = now + timedelta(days=1)
        return _start_of_day(d), _end_of_day(d)
    if period == "this_week":
        return _start_of_week(now), _end_of_week(now)
    if period == "last_week":
        start = _start_of_week(now) - timedelta(weeks=1)
        return start, _end_of_week(start)
    if period == "next_week":
        start = _start_of_week(now) + timedelta(weeks=1)
        return start, _end_of_week(start)
    if period == "this_month":
        return _start_of_month(now), _end_of_month(now)
    if period == "last_month":
        if now.month == 1:
            ref = now.replace(year=now.year - 1, month=12)
        else:
            ref = now.replace(month=now.month - 1)
        return _start_of_month(ref), _end_of_month(ref)
    if period == "next_month":
        if now.month == 12:
            ref = now.replace(year=now.year + 1, month=1)
        else:
            ref = now.replace(month=now.month + 1)
        return _start_of_month(ref), _end_of_month(ref)
    if period == "this_year":
        return _start_of_year(now), _end_of_year(now)
    if period == "last_year":
        ref = now.replace(year=now.year - 1)
        return _start_of_year(ref), _end_of_year(ref)
    if period == "last_n_days" and n > 0:
        start = _start_of_day(now) - timedelta(days=n - 1)
        return start, _end_of_day(now)
    if period == "next_n_days" and n > 0:
        end = _end_of_day(now) + timedelta(days=n - 1)
        return _start_of_day(now), end
    # Fallback: treat as "today"
    return _start_of_day(now), _end_of_day(now)


_ALL_PERIODS = (
    "today",
    "yesterday",
    "tomorrow",
    "this_week",
    "last_week",
    "next_week",
    "this_month",
    "last_month",
    "next_month",
    "this_year",
    "last_year",
)

_WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_WEEKDAYS_EN = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def build_time_context(tz_name: str = DEFAULT_TIMEZONE) -> dict:
    """Build a rich temporal context dict for the LLM.

    Returns current time (second-precise) and all common relative periods as
    ISO 8601 [start, end] ranges, plus metadata (weekday, week number, etc.).
    """
    now = _now(tz_name)

    periods: dict[str, dict[str, str]] = {}
    for period in _ALL_PERIODS:
        start, end = _period_range(now, period)
        periods[period] = {
            "start": _iso(start),
            "end": _iso(end),
        }

    # Also include last_7_days and last_30_days as convenience shortcuts
    for n in (7, 30):
        start, end = _period_range(now, "last_n_days", n=n)
        periods[f"last_{n}_days"] = {
            "start": _iso(start),
            "end": _iso(end),
        }

    iso_year, iso_week, iso_weekday = now.isocalendar()

    return {
        "now": _iso(now),
        "timezone": tz_name,
        "utc_offset": now.strftime("%z"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week_fr": _WEEKDAYS_FR[now.weekday()],
        "day_of_week_en": _WEEKDAYS_EN[now.weekday()],
        "day_of_year": now.timetuple().tm_yday,
        "week_number": iso_week,
        "iso_year": iso_year,
        "month_name_fr": (
            "janvier",
            "février",
            "mars",
            "avril",
            "mai",
            "juin",
            "juillet",
            "août",
            "septembre",
            "octobre",
            "novembre",
            "décembre",
        )[now.month - 1],
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "utc_now": _iso(datetime.now(UTC)),
        "periods": periods,
    }


def format_time_context(ctx: dict) -> str:
    """Format the time context as a human-readable string for evidence content."""
    lines = [
        f"Current time: {ctx['now']} ({ctx['timezone']})",
        f"Date: {ctx['date']}",
        f"Time: {ctx['time']}",
        f"Day: {ctx['day_of_week_fr']} ({ctx['day_of_week_en']}), day {ctx['day_of_year']} of the year",
        f"Week number: {ctx['week_number']} (ISO year {ctx['iso_year']})",
        f"Month: {ctx['month_name_fr']} {ctx['year']}",
        f"UTC time: {ctx['utc_now']}",
        "",
        "Relative periods (start → end, ISO 8601, second-precise):",
    ]
    for name, bounds in ctx["periods"].items():
        lines.append(f"  {name}: {bounds['start']} → {bounds['end']}")
    return "\n".join(lines)
