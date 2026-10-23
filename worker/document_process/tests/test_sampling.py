import math

import pytest

from app import sampling
from app.tasks import _shared
from app.windows import sliding_windows


def _windows(**changes):
    return {**_shared.PIPELINE_WINDOW_DEFAULTS, **changes}


# -- the draw ---------------------------------------------------------------------------------------------------


def test_the_same_seed_draws_the_same_windows():
    windows = sliding_windows(900, 2, 2)

    assert sampling.select_windows(windows, 40, seed=7) == sampling.select_windows(windows, 40, seed=7)
    assert sampling.select_windows(windows, 40, seed=7) != sampling.select_windows(windows, 40, seed=8)


def test_the_seed_is_the_file_s_not_the_document_s_and_each_step_has_its_own():
    assert sampling.seed_for("doc-1", "abc", "qa") == sampling.seed_for("doc-2", "abc", "qa")
    assert sampling.seed_for("doc-1", "abc", "qa") != sampling.seed_for("doc-1", "abc", "entities")
    assert sampling.seed_for("doc-1", None, "qa") != sampling.seed_for("doc-2", None, "qa")


def test_every_slice_of_the_document_has_a_window():
    """What a draw at random alone does not give: with 33 windows out of 450, no stretch is left bare."""
    windows = sliding_windows(900, 2, 2)

    for seed in range(50):
        chosen = sampling.select_windows(windows, 33, seed)
        assert len(chosen) == 33 and len(set(chosen)) == 33
        positions = sorted(windows.index(window) for window in chosen)
        for index, (start, end) in enumerate(sampling._slices(len(windows), 33)):
            assert start <= positions[index] < end


def test_the_windows_come_back_in_the_order_of_the_document():
    chosen = sampling.select_windows(sliding_windows(300, 2, 2), 20, seed=3)

    assert chosen == sorted(chosen)


def test_asking_for_as_many_windows_as_there_are_gives_them_all():
    windows = sliding_windows(10, 2, 2)

    assert sampling.select_windows(windows, 5, seed=1) == windows
    assert sampling.select_windows(windows, 99, seed=1) == windows
    assert sampling.select_windows(windows, 0, seed=1) == []


def test_blank_windows_are_only_drawn_when_there_are_not_enough_others():
    windows = sliding_windows(20, 2, 2)  # 10 windows
    blank = {(1, 2), (3, 4), (5, 6), (7, 8)}

    def usable(window):
        return window not in blank

    assert not blank & set(sampling.select_windows(windows, 6, seed=1, usable=usable))
    # Only six are usable: asking for eight takes all of them, then blank ones to make up.
    chosen = sampling.select_windows(windows, 8, seed=1, usable=usable)
    assert len(chosen) == 8 and set(windows) - blank <= set(chosen)


def test_a_window_is_usable_when_its_pages_hold_some_text():
    usable = sampling.window_has_text({1: "x" * 10, 2: "   ", 3: "y" * 50})

    assert not usable((1, 2))
    assert usable((2, 3))
    assert not usable((4, 5))


@pytest.mark.parametrize(
    ("available", "percent", "cap", "expected"),
    [(225, 20, None, 45), (225, 20, 30, 30), (225, 100, None, 225), (3, 1, None, 1), (10, 50, 99, 5), (0, 50, None, 0)],
)
def test_a_share_of_the_windows_is_at_least_one_and_at_most_the_cap(available, percent, cap, expected):
    assert sampling.count_for_percent(available, percent, cap) == expected


@pytest.mark.parametrize(
    ("available", "max_questions", "per_window", "expected"),
    [
        (450, 100, 3, (33, 3)),
        (450, None, 3, (450, 3)),
        (10, 100, 3, (10, 3)),
        (450, 2, 3, (1, 2)),
        (450, 3, 3, (1, 3)),
        (0, 100, 3, (0, 3)),
    ],
)
def test_the_questions_asked_never_go_over_the_cap(available, max_questions, per_window, expected):
    plan = sampling.qa_plan(available, max_questions, per_window)

    assert plan == expected
    if max_questions is not None:
        assert plan[0] * plan[1] <= max_questions or available == 0


def test_the_disjoint_windows_are_side_by_side():
    assert sampling.disjoint_windows(9, 4) == [(1, 4), (5, 8), (9, 9)]
    assert math.ceil(900 / 4) == len(sampling.disjoint_windows(900, 4))


# -- when it applies ---------------------------------------------------------------------------------------------


def test_a_document_is_sampled_above_the_minimum_only():
    windows = _windows(sampling_min_pages=100)

    assert not sampling.applies(100, windows)
    assert sampling.applies(101, windows)


# -- the pages of the summary --------------------------------------------------------------------------------------


def test_the_whole_document_is_read_by_default_and_when_it_is_short():
    assert sampling.summary_segments(900, _windows()) is None
    assert sampling.summary_segments(100, _windows(summary_mode="percent", summary_percent=30)) is None


def test_a_share_is_read_half_at_the_start_and_half_at_the_end():
    windows = _windows(summary_mode="percent", summary_percent=30)

    assert sampling.summary_segments(900, windows) == [(1, 135), (766, 900)]


def test_an_odd_share_still_reads_the_pages_it_rounds_up_to():
    segments = sampling.summary_segments(101, _windows(summary_mode="percent", summary_percent=25))

    assert segments == [(1, 13), (89, 101)]  # ⌈101 × 25 %⌉ = 26 pages, 13 and 13


def test_a_start_and_an_end_set_apart_replace_the_share():
    windows = _windows(summary_mode="percent", summary_percent=90, summary_head_percent=20, summary_tail_percent=5)

    assert sampling.summary_segments(200, windows) == [(1, 40), (191, 200)]


def test_a_start_alone_reads_only_the_start():
    windows = _windows(summary_mode="percent", summary_head_percent=10)

    assert sampling.summary_segments(500, windows) == [(1, 50)]


def test_a_share_that_covers_the_document_reads_it_all():
    assert sampling.summary_segments(500, _windows(summary_mode="percent", summary_percent=100)) is None
    assert (
        sampling.summary_segments(
            500, _windows(summary_mode="percent", summary_head_percent=60, summary_tail_percent=40)
        )
        is None
    )


def test_given_pages_are_read_clamped_to_the_document_and_merged():
    windows = _windows(summary_mode="pages", summary_page_ranges="1-5, 4-9, 300-, 900-950, 40")

    assert sampling.summary_segments(400, windows) == [(1, 9), (40, 40), (300, 400)]


def test_pages_beyond_the_document_give_the_whole_document():
    windows = _windows(summary_mode="pages", summary_page_ranges="1000-1100")

    assert sampling.summary_segments(400, windows) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("7", [(7, 7)]),
        ("1-5, 40-45", [(1, 5), (40, 45)]),
        (" 90 - ", [(90, None)]),
        ("3,3-4,", [(3, 3), (3, 4)]),
        # What the backend refuses is ignored here, never read as something else.
        ("a, 5-2, 0-3, 1 2, 6", [(6, 6)]),
    ],
)
def test_page_ranges_are_read_like_the_backend_reads_them(text, expected):
    assert sampling.parse_page_ranges(text) == expected
