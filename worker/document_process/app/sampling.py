"""What to read of a long document (#372): the windows and pages the summary, the QA pairs and the entities work on.

Above `sampling_min_pages` pages a collection may ask for only a part of a document. Nothing here calls a model or
the network: it only decides, from the settings, which windows or pages are worth the calls - always the same ones
for the same file, so that a rerun, a reuse (#300) or a lane that recomputes its windows (#370) agree.

The chunks do not go through here: they always cover every page."""

import hashlib
import math
import random
import re
from collections.abc import Callable
from typing import Any

from app.windows import sliding_windows

Window = tuple[int, int]

# A window with less text than this has nothing to ask a question about nor to extract an entity from.
MIN_TEXT_CHARS = 40


def applies(total_pages: int, windows: dict[str, Any]) -> bool:
    """Whether the document is long enough to be sampled: above `sampling_min_pages` pages."""
    return total_pages > windows["sampling_min_pages"]


def seed_for(document_id: str, content_hash: str | None, step: str) -> int:
    """The same file gives the same seed - whatever its document, so that two documents of one file read the same
    pages - and each step has its own, so that they do not all draw the same positions."""
    digest = hashlib.sha256(f"{content_hash or document_id}:{step}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def disjoint_windows(total_pages: int, size: int) -> list[Window]:
    """The windows the draw is made from: side by side, none over another, so that a share of them is the same
    share of the pages (windows that slide by one page would cover four times as many pages as they are drawn
    for)."""
    size = max(size, 1)
    return sliding_windows(total_pages, size, size)


def _stratified(items: list[Window], count: int, rng: random.Random) -> list[Window]:
    """`count` of the items, one at random in each of `count` slices of the list, in order: spread over the whole
    document, where a draw at random alone leaves holes."""
    if count >= len(items):
        return list(items)
    if count <= 0:
        return []
    return [items[rng.randrange(start, end)] for start, end in _slices(len(items), count)]


def _slices(size: int, count: int) -> list[tuple[int, int]]:
    """`count` consecutive slices of range(size), as even as can be, none empty (count <= size)."""
    return [(index * size // count, (index + 1) * size // count) for index in range(count)]


def select_windows(
    windows: list[Window], count: int, seed: int, usable: Callable[[Window], bool] | None = None
) -> list[Window]:
    """`count` of the windows, spread over the document, the same ones for the same seed - all of them when `count`
    is not smaller than their number. The windows `usable` rejects (a blank page) are left aside, and only drawn
    when there are not enough others. In the order of the document."""
    if count >= len(windows):
        return list(windows)
    rng = random.Random(seed)
    good = [window for window in windows if usable is None or usable(window)]
    chosen = _stratified(good, count, rng)
    if len(chosen) < count:
        kept = set(good)
        rest = [window for window in windows if window not in kept]
        chosen += _stratified(rest, count - len(chosen), rng)
    return sorted(chosen)


def count_for_percent(available: int, percent: int, max_windows: int | None = None) -> int:
    """How many of `available` windows a share asks for: at least one, at most `max_windows` when there is a cap."""
    if available <= 0:
        return 0
    wanted = max(1, math.ceil(available * percent / 100))
    if max_windows is not None:
        wanted = min(wanted, max_windows)
    return min(wanted, available)


def qa_plan(available: int, max_questions: int | None, per_window: int) -> tuple[int, int]:
    """(windows to draw, questions to ask in each) so that the document has at most `max_questions`: with no cap,
    every window and `per_window`. A cap under `per_window` is one window asked for that many."""
    if max_questions is None:
        return available, per_window
    if max_questions < per_window:
        return min(1, available), max(max_questions, 1)
    return min(available, max_questions // per_window), per_window


def window_has_text(pages_text: dict[int, str]) -> Callable[[Window], bool]:
    """Usable windows for `select_windows`: those whose pages hold more than MIN_TEXT_CHARS characters together."""

    def usable(window: Window) -> bool:
        start, end = window
        return sum(len(pages_text.get(number, "").strip()) for number in range(start, end + 1)) >= MIN_TEXT_CHARS

    return usable


def plan_qa(
    total_pages: int, windows: dict[str, Any], pages_text: dict[int, str], seed: int
) -> tuple[list[Window], int, bool]:
    """(windows to ask the questions on, questions to ask in each, whether they were drawn). Every window, as before,
    unless the document is long enough and the collection caps its questions: then `qa_max_questions` is the most
    the document gets, from windows drawn side by side over all of it."""
    per_window, cap = windows["qa_questions_per_window"], windows["qa_max_questions"]
    if not applies(total_pages, windows) or cap is None:
        return sliding_windows(total_pages, windows["qa_window_pages"], windows["qa_slide_pages"]), per_window, False
    pool = disjoint_windows(total_pages, windows["qa_window_pages"])
    count, asked = qa_plan(len(pool), cap, per_window)
    return select_windows(pool, count, seed, window_has_text(pages_text)), asked, True


def plan_entities(
    total_pages: int, windows: dict[str, Any], pages_text: dict[int, str], seed: int
) -> tuple[list[Window], bool]:
    """(windows to extract the entities from, whether they were drawn). Every window, as before, unless the
    document is long enough and the collection asks for a share of them (or caps their number)."""
    percent, cap = windows["extraction_percent"], windows["extraction_max_windows"]
    if not applies(total_pages, windows) or (percent >= 100 and cap is None):
        return sliding_windows(
            total_pages, windows["extraction_window_pages"], windows["extraction_slide_pages"]
        ), False
    pool = disjoint_windows(total_pages, windows["extraction_window_pages"])
    count = count_for_percent(len(pool), percent, cap)
    return select_windows(pool, count, seed, window_has_text(pages_text)), True


# -- the pages the summary reads ------------------------------------------------------------------------------

_RANGE = re.compile(r"^(\d+)(?:(-)(\d*))?$")


def parse_page_ranges(text: str) -> list[tuple[int, int | None]]:
    """ "1-5, 40-45, 90-" -> [(1, 5), (40, 45), (90, None)] - None for "to the end". The backend has the same parser
    (app/core/page_ranges.py), which refuses what is not: a value it let through is read here."""
    ranges: list[tuple[int, int | None]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        found = _RANGE.match(re.sub(r"\s*-\s*", "-", part))
        if not found:
            continue
        first = int(found.group(1))
        last = (int(found.group(3)) if found.group(3) else None) if found.group(2) else first
        if first >= 1 and (last is None or last >= first):
            ranges.append((first, last))
    return ranges


def _merge(segments: list[Window]) -> list[Window]:
    merged: list[Window] = []
    for start, end in sorted(segments):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def summary_segments(total_pages: int, windows: dict[str, Any]) -> list[Window] | None:
    """The stretches of pages the summary reads, in order (first, last, inclusive) - None for the whole document: the
    mode asks for it, the stretches cover it, or the document is not long enough to be sampled."""
    mode = windows["summary_mode"]
    if mode == "all" or not applies(total_pages, windows):
        return None
    if mode == "percent":
        head, tail = windows.get("summary_head_percent"), windows.get("summary_tail_percent")
        if head is not None or tail is not None:
            head_pages = math.ceil(total_pages * (head or 0) / 100)
            tail_pages = math.ceil(total_pages * (tail or 0) / 100)
        else:
            read = math.ceil(total_pages * windows["summary_percent"] / 100)
            head_pages = math.ceil(read / 2)
            tail_pages = read - head_pages
        segments = []
        if head_pages:
            segments.append((1, head_pages))
        if tail_pages:
            segments.append((total_pages - tail_pages + 1, total_pages))
    else:
        segments = [
            (first, min(last if last is not None else total_pages, total_pages))
            for first, last in parse_page_ranges(windows["summary_page_ranges"])
            if first <= total_pages
        ]
    merged = _merge(segments)
    if not merged or sum(end - start + 1 for start, end in merged) >= total_pages:
        return None
    return merged
