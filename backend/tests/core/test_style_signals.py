"""What a 👍/👎 says of the style of an answer (#285), by rules: what is said is read, what is rated is measured, one
vote settles nothing, a signal fades, and a contradiction cancels."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core import style_signals as s

LONG = "mot " * 700
SHORT = "Trois jours."
TABLE = "| a | b |\n|---|---|\n| 1 | 2 |\n" + "texte " * 120


def dims(value: str, reasons: list[str] | None = None, comment: str | None = None, answer: str = "x" * 1000):
    return sorted(
        (signal.dimension, signal.direction, signal.weight)
        for signal in s.signals_of(value, reasons or [], comment, answer)
    )


@pytest.mark.parametrize(
    "comment, expected",
    [
        ("Trop long !", ("verbosity", -1)),
        ("c'est trop verbeux", ("verbosity", -1)),
        ("Je voudrais une réponse plus courte", ("verbosity", -1)),
        ("Too long for me", ("verbosity", -1)),
        ("Beaucoup trop de texte", ("verbosity", -1)),
        ("Trop court, développe", ("verbosity", 1)),
        ("Pas assez détaillé", ("verbosity", 1)),
        ("Plus de détails svp", ("verbosity", 1)),
        ("Mets-le en tableau", ("table", 1)),
        ("Sous forme de tableau, merci", ("table", 1)),
        ("Pas de tableau s'il te plaît", ("table", -1)),
        ("Trop de tableaux", ("table", -1)),
        ("sans tableau", ("table", -1)),
    ],
)
def test_what_a_person_says_of_the_length_or_the_form_is_a_signal_of_full_weight(comment, expected):
    signals = [(d, direction, w) for d, direction, w in dims("down", comment=comment, answer="x" * 1000)]

    assert (*expected, s.SAID) in signals


@pytest.mark.parametrize(
    "comment", ["Pas trop long, merci", "Ce n'est pas trop court", "Parfait", "La source est fausse", ""]
)
def test_a_comment_that_says_nothing_of_the_style_or_says_the_opposite_is_no_signal(comment):
    assert dims("down", comment=comment, answer="x" * 1000) == []


def test_what_is_said_is_read_without_case_or_accents():
    assert ("verbosity", -1, s.SAID) in dims("down", comment="TRÈS LONG ? TROP LONGUE, OUI")
    assert ("verbosity", 1, s.SAID) in dims("down", comment="PAS ASSEZ DÉTAILLÉ")


def test_a_down_about_the_facts_the_sources_or_the_tone_says_nothing_of_the_style():
    for reason in ("incorrect_answer", "questionable_sources", "inappropriate_tone", "other"):
        assert dims("down", [reason], None, LONG) == []
        assert dims("down", [reason], None, SHORT) == []


def test_a_down_for_not_being_useful_on_a_long_answer_leans_to_concise_but_never_on_a_short_one():
    assert dims("down", ["not_useful"], None, LONG) == [("verbosity", -1, s.MEASURED)]
    assert dims("down", ["not_useful"], None, SHORT) == []


def test_an_up_reinforces_what_the_rated_answer_was():
    assert dims("up", answer=SHORT) == [("verbosity", -1, s.MEASURED)]
    assert dims("up", answer=LONG) == [("verbosity", 1, s.MEASURED)]
    assert ("table", 1, s.MEASURED) in dims("up", answer=TABLE)
    assert dims("up", answer="x" * 1000) == []


def test_a_measure_weighs_less_than_a_word_and_one_vote_is_never_enough():
    assert s.MEASURED < s.SAID < s.THRESHOLD
    assert 2 * s.SAID >= s.THRESHOLD and s.SAID + 2 * s.MEASURED >= s.THRESHOLD and 2 * s.MEASURED < s.THRESHOLD


def test_a_signal_fades_by_half_each_half_life_and_never_gains():
    now = datetime.now(UTC)

    assert s.decayed(1.0, 0, 30) == pytest.approx(1.0)
    assert s.decayed(1.0, 30, 30) == pytest.approx(0.5)
    assert s.decayed(1.0, 90, 30) == pytest.approx(0.125)
    assert s.decayed(1.0, -5, 30) == pytest.approx(1.0)
    assert s.age_in_days(now - timedelta(days=3), now) == pytest.approx(3)


def test_each_side_of_each_dimension_has_a_sentence_and_the_two_sides_share_a_key():
    for dimension in ("verbosity", "table"):
        assert s.LEARNED[(dimension, 1)][0] == s.LEARNED[(dimension, -1)][0]
        assert s.LEARNED[(dimension, 1)][1] != s.LEARNED[(dimension, -1)][1]
