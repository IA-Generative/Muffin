"""Les périodes relatives du time tool, y compris les jours qui n'existent pas dans le mois voisin."""

from datetime import datetime

import pytest

from app.graph.services.time_tool import _period_range


@pytest.mark.parametrize(
    ("now", "period", "start", "end"),
    [
        (datetime(2026, 10, 31, 12), "last_month", datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59)),
        (datetime(2026, 10, 31, 12), "next_month", datetime(2026, 11, 1), datetime(2026, 11, 30, 23, 59, 59)),
        (datetime(2026, 3, 31, 12), "last_month", datetime(2026, 2, 1), datetime(2026, 2, 28, 23, 59, 59)),
        (datetime(2026, 1, 31, 12), "last_month", datetime(2025, 12, 1), datetime(2025, 12, 31, 23, 59, 59)),
        (datetime(2026, 12, 31, 12), "next_month", datetime(2027, 1, 1), datetime(2027, 1, 31, 23, 59, 59)),
        (datetime(2028, 2, 29, 12), "last_year", datetime(2027, 1, 1), datetime(2027, 12, 31, 23, 59, 59)),
    ],
)
def test_a_relative_period_exists_whatever_the_day_of_the_month(now, period, start, end):
    assert _period_range(now, period) == (start, end)
