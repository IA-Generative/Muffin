"""What counts as a use of a collection (#286), and how it ages: counting, and no model."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core import habits as h


def test_a_citation_weighs_more_than_an_attachment_and_one_use_is_never_a_habit():
    assert h.CITED > h.PINNED > 0
    assert h.CITED < h.THRESHOLD <= 2 * h.CITED and 4 * h.PINNED >= h.THRESHOLD > 3 * h.PINNED
    assert 0 < h.FORGET_BELOW < h.THRESHOLD


def test_a_score_loses_half_each_half_life_and_never_gains():
    now = datetime.now(UTC)

    assert h.faded(4.0, now, now, 30) == pytest.approx(4.0)
    assert h.faded(4.0, now - timedelta(days=30), now, 30) == pytest.approx(2.0)
    assert h.faded(4.0, now - timedelta(days=90), now, 30) == pytest.approx(0.5)
    assert h.faded(4.0, now + timedelta(days=3), now, 30) == pytest.approx(4.0)


def test_the_weight_in_the_routing_is_between_zero_and_one():
    assert h.weight_of(0) == 0 and h.weight_of(-3) == 0
    assert h.weight_of(h.FULL_WEIGHT_SCORE / 2) == pytest.approx(0.5)
    assert h.weight_of(100) == 1.0


def test_the_routing_bonus_is_a_few_per_cent_at_most():
    assert 0 < h.MAX_ROUTING_BONUS <= 0.15


def test_what_a_habit_says_to_the_person_is_one_line_with_the_name_of_the_collection():
    assert h.sentence("Règlements") == "Consulte souvent la collection « Règlements »"
    assert h.sentence("Un\nnom   étrange") == "Consulte souvent la collection « Un nom étrange »"
    assert len(h.sentence("x" * 500)) < 200


def test_the_key_of_a_habit_is_made_of_the_collection_and_fits_the_column():
    identifier = uuid.uuid4()

    assert h.key_of(identifier) == f"collection-{identifier}" and len(h.key_of(identifier)) <= 80
