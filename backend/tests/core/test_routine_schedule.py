"""The dates of a routine (#524): the owner's wall-clock times across daylight saving, short months, one run after an
outage, and a rhythm that is checked."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.routine_schedule import (
    InvalidScheduleError,
    RoutineKind,
    Schedule,
    advance,
    first_run,
    minimum_gap,
    next_after,
    upcoming,
    validate,
)

PARIS = ZoneInfo("Europe/Paris")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def local(moment: datetime, zone: ZoneInfo = PARIS) -> datetime:
    return moment.astimezone(zone)


def daily(at: time = time(9, 0), timezone: str = "Europe/Paris") -> Schedule:
    return Schedule(RoutineKind.DAILY, timezone, time_of_day=at)


def test_every_day_at_nine_stays_at_nine_across_the_change_to_summer_time():
    # The night of 28 to 29 March 2026: Paris goes from UTC+1 to UTC+2.
    dates = upcoming(daily(), utc(2026, 3, 27, 12, 0), 4)

    assert [local(d).strftime("%d %H:%M") for d in dates] == ["28 09:00", "29 09:00", "30 09:00", "31 09:00"]
    assert [d.hour for d in dates] == [8, 7, 7, 7]  # nine o'clock is 8:00 UTC before the change, 7:00 after


def test_every_day_at_nine_stays_at_nine_across_the_change_to_winter_time():
    # The night of 24 to 25 October 2026: back to UTC+1.
    dates = upcoming(daily(), utc(2026, 10, 23, 12, 0), 3)

    assert [local(d).strftime("%d %H:%M") for d in dates] == ["24 09:00", "25 09:00", "26 09:00"]
    assert [d.hour for d in dates] == [7, 8, 8]


def test_a_time_that_does_not_exist_runs_once_that_day_and_one_that_exists_twice_runs_once():
    skipped = upcoming(daily(time(2, 30)), utc(2026, 3, 28, 12, 0), 3)  # 2:30 on 29 March 2026 does not exist
    repeated = upcoming(daily(time(2, 30)), utc(2026, 10, 24, 12, 0), 3)  # 2:30 on 25 October exists twice

    assert [d.date().isoformat() for d in (local(d) for d in skipped)] == ["2026-03-29", "2026-03-30", "2026-03-31"]
    assert [d.date().isoformat() for d in (local(d) for d in repeated)] == ["2026-10-25", "2026-10-26", "2026-10-27"]


def test_the_zone_of_the_owner_decides_the_hour():
    montreal = upcoming(daily(time(9, 0), "America/Montreal"), utc(2026, 1, 10, 0, 0), 1)[0]

    assert montreal == utc(2026, 1, 10, 14, 0)  # UTC-5 in winter


def test_a_date_is_strictly_after_the_moment_it_is_computed_from():
    nine = utc(2026, 4, 6, 7, 0)  # 9:00 in Paris, in summer time

    assert next_after(daily(), nine) == nine + timedelta(days=1)
    assert next_after(daily(), nine - timedelta(seconds=1)) == nine


def test_weekly_goes_to_the_next_chosen_day():
    schedule = Schedule(RoutineKind.WEEKLY, time_of_day=time(8, 30), weekdays=[0, 3])  # Monday and Thursday

    dates = upcoming(schedule, utc(2026, 4, 6, 12, 0), 4)  # a Monday, after 8:30

    assert [(local(d).strftime("%a %d"), local(d).hour) for d in dates] == [
        ("Thu 09", 8),
        ("Mon 13", 8),
        ("Thu 16", 8),
        ("Mon 20", 8),
    ]


def test_monthly_on_the_31st_falls_on_the_last_day_of_the_shorter_months():
    schedule = Schedule(RoutineKind.MONTHLY, time_of_day=time(7, 0), day_of_month=31)

    dates = upcoming(schedule, utc(2026, 1, 15, 0, 0), 5)

    assert [local(d).strftime("%m-%d") for d in dates] == ["01-31", "02-28", "03-31", "04-30", "05-31"]


def test_monthly_on_the_29th_in_a_leap_year_and_not():
    schedule = Schedule(RoutineKind.MONTHLY, time_of_day=time(7, 0), day_of_month=29)

    leap = upcoming(schedule, utc(2028, 1, 30, 0, 0), 1)[0]
    plain = upcoming(schedule, utc(2027, 1, 30, 0, 0), 1)[0]

    assert (local(leap).month, local(leap).day) == (2, 29) and (local(plain).month, local(plain).day) == (2, 28)


def test_by_hours_the_dates_are_counted_from_the_first_run_without_drift():
    schedule = Schedule(RoutineKind.INTERVAL, interval_minutes=120)
    now = utc(2026, 4, 6, 10, 7)

    first = first_run(schedule, now)
    second = advance(schedule, first, first + timedelta(minutes=3))  # the sweep got to it three minutes late

    assert first == utc(2026, 4, 6, 12, 7) and second == utc(2026, 4, 6, 14, 7)


def test_a_routine_missed_during_an_outage_has_one_next_date_after_now_not_a_backlog():
    interval = Schedule(RoutineKind.INTERVAL, interval_minutes=60)
    due = utc(2026, 4, 6, 8, 0)
    back = utc(2026, 4, 6, 17, 20)  # nine missed dates

    assert advance(interval, due, back) == utc(2026, 4, 6, 18, 0)
    assert advance(daily(), utc(2026, 4, 1, 7, 0), back) == utc(2026, 4, 7, 7, 0)
    weekly = Schedule(RoutineKind.WEEKLY, time_of_day=time(9, 0), weekdays=[0])
    assert local(advance(weekly, utc(2026, 3, 2, 8, 0), back)).strftime("%Y-%m-%d") == "2026-04-13"


def test_the_gap_between_two_runs_is_what_the_minimal_interval_is_compared_to():
    assert minimum_gap(Schedule(RoutineKind.INTERVAL, interval_minutes=90)) == timedelta(minutes=90)
    assert minimum_gap(daily()) == timedelta(days=1)
    assert minimum_gap(Schedule(RoutineKind.WEEKLY, time_of_day=time(9), weekdays=[0, 1])) == timedelta(days=1)
    assert minimum_gap(Schedule(RoutineKind.WEEKLY, time_of_day=time(9), weekdays=[2])) == timedelta(days=7)


@pytest.mark.parametrize(
    "schedule",
    [
        Schedule(RoutineKind.INTERVAL),
        Schedule(RoutineKind.INTERVAL, interval_minutes=5),
        Schedule(RoutineKind.INTERVAL, interval_minutes=60 * 24 * 40),
        Schedule(RoutineKind.DAILY),
        Schedule(RoutineKind.WEEKLY, time_of_day=time(9)),
        Schedule(RoutineKind.WEEKLY, time_of_day=time(9), weekdays=[7]),
        Schedule(RoutineKind.MONTHLY, time_of_day=time(9)),
        Schedule(RoutineKind.MONTHLY, time_of_day=time(9), day_of_month=32),
        Schedule(RoutineKind.DAILY, "Nowhere/City", time_of_day=time(9)),
    ],
)
def test_a_rhythm_that_lacks_something_or_goes_out_of_bounds_is_refused(schedule):
    with pytest.raises(InvalidScheduleError):
        validate(schedule)


def test_the_minimal_interval_is_the_one_given():
    schedule = Schedule(RoutineKind.INTERVAL, interval_minutes=60)

    validate(schedule, 60)
    with pytest.raises(InvalidScheduleError):
        validate(schedule, 120)
