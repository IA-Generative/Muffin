"""Where a passage is on a page (#350): from text or an interval of characters to the rectangles to frame on the
page's screenshot.

The lines of a page (`PageTextBox`) give, for each line and each word, its box - normalized between 0 and 1 - and its
interval of characters in the page's content. A passage found in the content is therefore one rectangle per line it
covers, tight around its words."""

import re
from collections.abc import Sequence

from app.models.document import PageTextBox

# A value that is everywhere on the page ("Paris") would drown it in rectangles and teach nothing more.
MAX_OCCURRENCES = 10
_MIN_MATCH = 3
_FIRST_WORDS = 8
_ELLIPSIS_EDGES = re.compile(r"^(?:\.{2,}|…|\s)+|(?:\.{2,}|…|\s)+$")
# The fragments of a passage: its paragraphs - a chunk is paragraphs joined by blank lines, each on one page -
# and the pieces an excerpt is truncated into with "...". The same cut as the source modal's own highlighting
# (frontend/src/utils/highlightPassage.ts).
_FRAGMENT_SPLIT = re.compile(r"\n\s*\n|\.{2,}|…")

Span = tuple[int, int]


def _loose(fragment: str) -> re.Pattern[str] | None:
    """The words of the fragment separated by any whitespace (an excerpt is flattened, the content keeps its line
    breaks), whatever the case - the model reformats."""
    words = fragment.split()
    return re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE) if words else None


def find_spans(content: str, text: str, limit: int = MAX_OCCURRENCES) -> list[Span]:
    """The occurrences of `text` in `content`, in order, up to `limit`."""
    pattern = _loose(text)
    if pattern is None or not content:
        return []
    limit = min(limit, MAX_OCCURRENCES)
    spans = []
    for match in pattern.finditer(content):
        if match.end() - match.start() >= _MIN_MATCH:
            spans.append(match.span())
        if len(spans) >= limit:
            break
    return spans


def _find_fragment(content: str, fragment: str, start: int) -> Span | None:
    # The fragment whole, then its first words: an excerpt can be a summary of the zone, so it may not match
    # word for word.
    for candidate in (fragment, " ".join(fragment.split()[:_FIRST_WORDS])):
        pattern = _loose(candidate)
        if pattern is None:
            continue
        # After the previous fragment when it can be (they come in order); anywhere otherwise.
        for origin in (start, 0):
            match = pattern.search(content, origin)
            if match and match.end() - match.start() >= _MIN_MATCH:
                return match.span()
    return None


def locate_passage(content: str, passage: str | None, max_occurrences: int = 1) -> list[Span]:
    """Where the passage is in the page's content, as intervals of characters: each of its fragments, once and in
    order. A short text asked with `max_occurrences` above 1 gives its occurrences instead. Nothing found, nothing
    returned - never an approximate place."""
    cleaned = _ELLIPSIS_EDGES.sub("", passage or "").strip()
    fragments = [fragment.strip() for fragment in _FRAGMENT_SPLIT.split(cleaned) if fragment.strip()]
    if not content or not fragments:
        return []
    if len(fragments) == 1 and max_occurrences > 1:
        return find_spans(content, fragments[0], min(max_occurrences, MAX_OCCURRENCES))
    spans: list[Span] = []
    cursor = 0
    for fragment in fragments:
        span = _find_fragment(content, fragment, cursor)
        if span is not None:
            spans.append(span)
            cursor = span[1]
    spans.sort()
    merged: list[Span] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            continue  # overlaps the previous one
        merged.append((start, end))
    return merged


def _overlaps(start: int | None, end: int | None, span_start: int, span_end: int) -> bool:
    return start is not None and end is not None and start < span_end and end > span_start


def _union(rects: Sequence[dict]) -> dict[str, float]:
    return {
        "x_min": min(rect["x_min"] for rect in rects),
        "y_min": min(rect["y_min"] for rect in rects),
        "x_max": max(rect["x_max"] for rect in rects),
        "y_max": max(rect["y_max"] for rect in rects),
    }


def rects_for_span(boxes: Sequence[PageTextBox], start: int, end: int) -> list[dict[str, float]]:
    """One rectangle per line the interval `[start, end)` touches, tight around the words it covers (the whole line
    when it has no detailed words). A line with no interval (OCR) is left out."""
    rects = []
    for box in boxes:
        if not _overlaps(box.char_start, box.char_end, start, end):
            continue
        words = [w for w in box.words or [] if _overlaps(w.get("char_start"), w.get("char_end"), start, end)]
        rects.append(
            _union(words) if words else {"x_min": box.x_min, "y_min": box.y_min, "x_max": box.x_max, "y_max": box.y_max}
        )
    return rects


# A chunk that crosses this many pages is not a chunk of pages: what an old one without intervals could claim.
_MAX_CHUNK_PAGES = 20


def chunk_pages_of(extras: dict) -> list[int]:
    """The pages a chunk is on, in order: from its intervals (#353), else from its first and last page, which a chunk
    made before them has."""
    spans = extras.get("spans")
    if isinstance(spans, list) and spans:
        return sorted({span["page"] for span in spans if isinstance(span, dict) and isinstance(span.get("page"), int)})
    first, last = extras.get("page_start"), extras.get("page_end")
    if isinstance(first, int) and isinstance(last, int) and first <= last < first + _MAX_CHUNK_PAGES:
        return list(range(first, last + 1))
    return []


def chunk_spans_on(extras: dict, page_number: int, content_length: int) -> list[Span] | None:
    """The intervals of a chunk on this page, brought back into the page's content - None when the chunk has no
    intervals at all (made before they were kept: its text is looked for instead), an empty list when it has some
    but none on this page."""
    spans = extras.get("spans")
    if not isinstance(spans, list) or not spans:
        return None
    return [
        (span["start"], min(span["end"], content_length))
        for span in spans
        if isinstance(span, dict)
        and span.get("page") == page_number
        and isinstance(span.get("start"), int)
        and isinstance(span.get("end"), int)
        and span["start"] < min(span["end"], content_length)
    ]
