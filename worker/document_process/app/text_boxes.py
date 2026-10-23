"""The positioned text of a page (#350): its lines and words, each with its box and where it is in the page's text.

liteparse gives a page's `text_items` (a line each) and, asked for them, the `words` of each, in the page's own units,
origin at the top left. The backend wants boxes **normalized** between 0 and 1 against the page - they then land on the
screenshot whatever the scale it was rendered at - and, for each line and word, its interval of characters in the
page's text, which is what lets a passage found in that text be framed. The interval is None when the fragment is not
found there (OCR text is not always the text of the page): such a line can be read, not placed."""

from typing import Any

# What the backend accepts for a page (schemas/internal_document.py): beyond these, the page is cut, not refused.
MAX_LINES = 5000
MAX_WORDS_PER_LINE = 1000


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _box(item: Any, width: float, height: float) -> dict[str, float] | None:
    """The item's box between 0 and 1, or None when it has no area on the page."""
    if item.width is None or item.height is None or item.width <= 0 or item.height <= 0:
        return None
    return {
        "x_min": _clamp(item.x / width),
        "y_min": _clamp(item.y / height),
        "x_max": _clamp((item.x + item.width) / width),
        "y_max": _clamp((item.y + item.height) / height),
    }


def _locate(text: str, haystack: str, cursor: int) -> tuple[int | None, int]:
    """Where `text` is in `haystack`, looking from `cursor` (the items come in reading order, which is the order of
    the page's text) - and the new cursor. The text itself, then without its surrounding blanks."""
    for candidate in (text, text.strip()):
        if not candidate:
            continue
        start = haystack.find(candidate, cursor)
        if start != -1:
            return start, start + len(candidate)
    return None, cursor


def build_text_boxes(page: Any) -> list[dict[str, Any]]:
    """The page's lines, each with its words: `[{"text", "x_min", ..., "char_start", "char_end", "words": [...]}]`,
    in the shape of the backend's `TextBoxIn`. Empty for a page that has no positioned text."""
    items = getattr(page, "text_items", None) or []
    width, height = getattr(page, "width", None), getattr(page, "height", None)
    if not items or not width or not height or width <= 0 or height <= 0:
        return []
    boxes: list[dict[str, Any]] = []
    cursor = 0
    for item in items:
        box = _box(item, width, height)
        if not item.text or box is None:
            continue
        start, found_end = _locate(item.text, page.text, cursor)
        # `_locate` gives the cursor back when it finds nothing: that is no end of anything.
        end = found_end if start is not None else None
        words = []
        word_cursor = start if start is not None else 0
        for word in (item.words or [])[:MAX_WORDS_PER_LINE]:
            word_box = _box(word, width, height)
            if not word.text or word_box is None:
                continue
            # Words come in order within their line: looked for inside the line's own interval.
            word_start, _ = (
                _locate(word.text, page.text[:end], word_cursor) if start is not None else (None, word_cursor)
            )
            if word_start is not None:
                word_cursor = word_start + len(word.text.strip() or word.text)
            words.append(
                {
                    "text": word.text[:500],
                    **word_box,
                    "char_start": word_start,
                    "char_end": word_start + len(word.text) if word_start is not None else None,
                }
            )
        boxes.append(
            {
                "text": item.text[:5000],
                **box,
                "char_start": start,
                "char_end": end,
                "words": words,
            }
        )
        if end is not None:
            cursor = end
        if len(boxes) >= MAX_LINES:
            break
    return boxes
